"""상장폐지 확정 기업 원문 이관 — NAS 아카이브 이동 + SD 백업 제거.

계획: docs/plans/collection_pipeline_restore_2026-07-31.md §6.4·§6.4b (결정 D1)
데일리 배선: scripts/collect_new.py `_sync_delisting_archive()` (⓪-4)
수동 CLI:   scripts/delisting_manage.py --archive / --sync-backup

원래 §6.4b 는 SD 정리를 "수동·연 1~2회"로 뒀는데, 2026-08-01 사용자 결정으로 **데일리 자동**이
됐다. 그래서 로직을 CLI 에서 여기로 옮긴다 — 자동 경로와 수동 경로가 각각 구현을 갖고
따로 굳는 것을 막기 위해서다(구현은 하나, 진입점만 둘).

무엇을 하고 무엇을 안 하나
──────────────────────────
  · NAS(PRIMARY)  raw_report/{시장}/{코드_이름}/  →  archive/delisted/{연도}/{코드_이름}/  **이동**
  · SD(BACKUP)    같은 폴더 **삭제** — NAS 아카이브에 실물이 있다는 것을 확인한 뒤에만
  · 삭제는 SD(백업)에만 일어난다. 원문 자체는 어떤 경우에도 지우지 않는다(결정 D1).

자동화하면서 새로 필요해진 가드
───────────────────────────────
  A1  한 실행당 이관 상한(MAX_ARCHIVE_PER_RUN). 판정 상한 G3(명부 경로 20건/일)보다 크지 않게
      둬서 **아카이브가 확정보다 빨리 번질 수 없게** 한다. 넘으면 그 실행은 멈추고 알린다.
  A2  SD 삭제 전 `assert_storage(require_backup=True)` — 빈 마운트포인트를 SD 로 오인하면
      전멸한다(§5.3.1 의 그 함정).
  A3  SD 삭제 전 NAS 아카이브 **실재 + 파일 수 대조**. 아카이브가 SD 보다 파일이 적으면
      이동이 덜 끝났거나 어긋난 것이므로 삭제하지 않고 넘어간다(경고).
  A4  전역 `rsync --delete` 를 쓰지 않는다. 확정+아카이브 확인된 폴더 목록만 rmtree.

되돌리기는 `scripts/delisting_manage.py --restore <corp_code> --apply` — 아카이브에서
원위치로 되돌리고 상태를 reinstated 로 푼다. SD 는 다음 데일리 미러가 다시 채운다.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import (
    ARCHIVE_ROOT, BACKUP_ROOT, PRIMARY_ROOT, assert_storage,
)

# A1 — 한 실행당 상한. collector.delisting.DAILY_CONFIRM_CAP_REGISTRY(=20)와 맞춘다.
# 하루에 확정될 수 있는 최대치와 같으므로, 정상 운영에서는 절대 걸리지 않는다.
# 걸린다면 확정이 비정상적으로 쌓였다는 뜻이고, 그때는 사람이 봐야 한다.
MAX_ARCHIVE_PER_RUN = 20


def _corp_dir(root: Path, market: Optional[str], corp_code: str) -> Optional[Path]:
    """raw_report/{시장}/{코드_이름}/ 을 찾는다. 이름 표기가 달라졌을 수 있어 코드로 탐색."""
    mroot = root / (market or "")
    if not mroot.is_dir():
        return None
    for child in mroot.iterdir():
        if child.is_dir() and child.name.startswith(corp_code):
            return child
    return None


def _dir_stats(path: Path) -> tuple[int, float]:
    """(파일 수, MB). 파일 수는 A3 대조용이라 정확해야 한다."""
    n, size = 0, 0
    for f in path.rglob("*"):
        if f.is_file():
            n += 1
            size += f.stat().st_size
    return n, size / 1024 ** 2


def archive_confirmed(apply: bool = False,
                      limit: int = MAX_ARCHIVE_PER_RUN) -> dict:
    """확정분 원문을 NAS 아카이브로 **이동**한다(삭제 아님, 결정 D1).

    Returns:
        {"moved": [(corp_code, corp_name, dst, mb)], "no_source": [(code, name)],
         "pending": int, "capped": bool, "errors": [(code, name, msg)]}
    """
    assert_storage(require_backup=False)
    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, corp_name, market FROM corporations
            WHERE delisting_status = 'confirmed' AND archive_path IS NULL
            ORDER BY corp_name
        """)).fetchall()

    out: dict = {"moved": [], "no_source": [], "errors": [],
                 "pending": len(rows), "capped": False}
    if not rows:
        return out

    # A1 — 상한 초과는 잘라내는 게 아니라 **전부 멈춘다**. 부분 실행하면 다음 날 또
    # 상한에 걸려 이상 상황이 조용히 지속된다.
    if len(rows) > limit:
        out["capped"] = True
        logger.error(f"[archive] A1 상한 초과 — 이관 대상 {len(rows)}개 > {limit}. "
                     f"이번 실행은 이관하지 않는다(사람 확인 필요).")
        return out

    year = str(date.today().year)
    for corp_code, corp_name, market in rows:
        src = _corp_dir(PRIMARY_ROOT, market, corp_code)
        if src is None:
            # 원문을 한 번도 받지 않았거나 이미 손으로 옮긴 기업. 결함이 아니다.
            out["no_source"].append((corp_code, corp_name))
            continue
        dst = ARCHIVE_ROOT / year / src.name
        _, mb = _dir_stats(src)
        if not apply:
            out["moved"].append((corp_code, corp_name, dst, mb))
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                # 같은 이름이 이미 아카이브에 있다 — 덮어쓰지 않는다(과거분 유실 방지).
                raise FileExistsError(f"아카이브 대상이 이미 존재: {dst}")
            shutil.move(str(src), str(dst))
            with get_session() as s:
                s.execute(text(
                    "UPDATE corporations SET archive_path = :p, updated_at = now() "
                    "WHERE corp_code = :c"), {"p": str(dst), "c": corp_code})
                s.commit()
            out["moved"].append((corp_code, corp_name, dst, mb))
            logger.info(f"[archive] 이관 {corp_name}({corp_code}) → {dst}  ({mb:.0f}MB)")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append((corp_code, corp_name, f"{type(exc).__name__}: {exc}"))
            logger.error(f"[archive] 이관 실패 {corp_name}({corp_code}): {exc}")
    return out


def purge_backup(apply: bool = False) -> dict:
    """SD 백업에서 아카이브 완료분 폴더를 제거한다(§6.4b).

    데일리 미러는 덧붙이기 전용이라 아카이브 이관분이 SD 에 그대로 남는다. 여기서 지우되
    **NAS 아카이브에 실물(파일 수 포함)이 확인된 폴더만** 지운다(A2·A3·A4).

    Returns:
        {"purged": [(code, name, path, mb)], "skipped": [(code, name, reason)],
         "errors": [...], "mb": float}
    """
    assert_storage(require_backup=True)          # A2
    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, corp_name, market, archive_path FROM corporations
            WHERE delisting_status = 'confirmed' AND archive_path IS NOT NULL
            ORDER BY corp_name
        """)).fetchall()

    out: dict = {"purged": [], "skipped": [], "errors": [], "mb": 0.0}
    for corp_code, corp_name, market, archive_path in rows:
        sd_dir = _corp_dir(BACKUP_ROOT, market, corp_code)
        if sd_dir is None:
            continue                              # 이미 정리됨 — 조용히 통과
        arc = Path(archive_path)
        # A3 — 원본 없이 백업만 지우는 사고 방지.
        if not arc.is_dir():
            out["skipped"].append((corp_code, corp_name,
                                   f"NAS 아카이브 없음({archive_path})"))
            continue
        arc_n, _ = _dir_stats(arc)
        sd_n, sd_mb = _dir_stats(sd_dir)
        if arc_n < sd_n:
            out["skipped"].append((corp_code, corp_name,
                                   f"아카이브 파일 수 부족(NAS {arc_n} < SD {sd_n})"))
            continue
        if not apply:
            out["purged"].append((corp_code, corp_name, sd_dir, sd_mb))
            out["mb"] += sd_mb
            continue
        try:
            shutil.rmtree(sd_dir)                 # A4 — 폴더 단위, 전역 --delete 아님
            out["purged"].append((corp_code, corp_name, sd_dir, sd_mb))
            out["mb"] += sd_mb
            logger.info(f"[archive] SD 정리 {corp_name}({corp_code}) {sd_dir} ({sd_mb:.0f}MB)")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append((corp_code, corp_name, f"{type(exc).__name__}: {exc}"))
            logger.error(f"[archive] SD 정리 실패 {corp_name}({corp_code}): {exc}")
    return out


def run_daily(apply: bool = True) -> dict:
    """데일리 진입점 — 이관 후 SD 정리까지. 이상 상황은 메일로 알린다.

    ★ 반드시 미러(⑥)보다 **먼저** 돌아야 한다. 원문이 raw_report 밖으로 나간 뒤에 미러가
      돌아야 방금 지운 SD 폴더를 다시 채우지 않는다.

    예외는 호출자에게 그대로 올린다 — 저장소 계약 위반(assert_storage)은 삼키면 안 된다.
    """
    # 상한은 호출 시점의 모듈 값을 쓴다(기본 인자로 굳히면 조정·테스트가 안 먹는다).
    a = archive_confirmed(apply=apply, limit=MAX_ARCHIVE_PER_RUN)
    alerts: list[str] = []

    if a["capped"]:
        alerts.append(f"이관 대상 {a['pending']}개가 상한 {MAX_ARCHIVE_PER_RUN}개를 넘어 "
                      f"이번 실행은 이관을 건너뛰었습니다. "
                      f"확인: scripts/delisting_manage.py --list")
    for code, name, msg in a["errors"]:
        alerts.append(f"이관 실패 {name}({code}): {msg}")

    p = purge_backup(apply=apply) if not a["capped"] else {
        "purged": [], "skipped": [], "errors": [], "mb": 0.0}
    for code, name, reason in p["skipped"]:
        alerts.append(f"SD 정리 보류 {name}({code}): {reason}")
    for code, name, msg in p["errors"]:
        alerts.append(f"SD 정리 실패 {name}({code}): {msg}")

    summary = {
        "archived": len(a["moved"]), "archive_no_source": len(a["no_source"]),
        "archive_capped": a["capped"], "archive_errors": len(a["errors"]),
        "backup_purged": len(p["purged"]), "backup_purged_mb": round(p["mb"], 1),
        "backup_skipped": len(p["skipped"]), "backup_errors": len(p["errors"]),
    }
    if a["moved"] or p["purged"]:
        logger.success(
            f"[archive] 상장폐지 원문 이관 {summary['archived']}개 · "
            f"SD 정리 {summary['backup_purged']}개({summary['backup_purged_mb']:.0f}MB)")
    if alerts:
        try:
            from scripts.notify import notify_failure
            notify_failure("상장폐지 원문 이관 — 확인 필요", "\n".join(alerts))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[archive] 알림 실패(비치명적): {exc}")
    return summary
