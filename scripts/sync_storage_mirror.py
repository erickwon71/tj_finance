"""NAS(primary) → SD(backup) 원문 미러 — **덧붙이기 전용**.

결정 D3'(2026-07-31): `--delete` 를 데일리에서 뺐다.
  측정 결과 상장폐지 10개사 원문 전체가 857MB(SD 여유 148GB 의 0.6%)라 `--delete` 로
  회수되는 용량이 사실상 없는데, 이 계획에서 유일하게 치명적인 연산이었다.
  · 심링크가 SD 를 가리키는 상태(드리프트)에서 `--delete` 를 돌리면 그날 받은 파일이
    "소스에 없는 파일"로 판정돼 삭제된다. DB 는 completed 인데 파일만 사라진다.
  · 소스(NAS)가 빈 마운트포인트면 SD 백업 218GB 가 통째로 지워진다.
  덧붙이기는 어떤 실패 모드에서도 기존 파일을 지우지 못한다.

아카이브로 옮긴 상장폐지 원문의 SD 정리는 `scripts/delisting_manage.py --sync-backup`
(수동, 연 1~2회)이 담당한다 — 전역 `--delete` 가 아니라 폴더 목록을 명시적으로 지운다.

⚠️ rsync 소스는 **심링크가 아니라 PRIMARY_ROOT 절대경로**다.
   심링크를 따라가면 드리프트 시 소스와 목적지가 같은 볼륨이 될 수 있다.

사용:
    python scripts/sync_storage_mirror.py            # 실행
    python scripts/sync_storage_mirror.py --dry-run  # 전송 대상만 확인
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import (
    BACKUP_ROOT, PRIMARY_ROOT, StorageContractError, assert_storage,
)

# 원문이 아닌 사이드카/제어 파일 — SD 가 HFS+ 라 macOS 가 `._*` 를 대량 생성한다.
# `.sync.ffs_*` = FreeFileSync 메타데이터. 사용자가 수동 동기화에 쓰던 도구의 DB 라
# rsync 가 덮어쓰면 그쪽 도구가 혼란스러워진다(재스캔만 하므로 무해하지만 불필요).
EXCLUDES = ["._*", ".DS_Store", ".tj_volume_id", ".tj_write_probe.*",
            ".sync.ffs_db", ".sync.ffs_lock"]

FREE_WARN_GB = 20     # 이하면 경고
FREE_STOP_GB = 5      # 이하면 중단


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def _log_run(status: str, files: int | None, sent_bytes: int | None,
             dur: float, message: str) -> None:
    """storage_sync_log 기록 — 미러 신선도 감시(§5.4)의 근거가 된다."""
    try:
        with get_session() as s:
            s.execute(text("""
                INSERT INTO storage_sync_log
                    (started_at, finished_at, status, files_sent, bytes_sent,
                     duration_sec, message)
                VALUES (:st, now(), :status, :files, :bytes, :dur, :msg)
            """), {"st": datetime.utcnow(), "status": status, "files": files,
                   "bytes": sent_bytes, "dur": dur, "msg": message[:2000]})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[mirror] 이력 기록 실패(비치명적): {type(exc).__name__}: {exc}")


def run_mirror(dry_run: bool = False) -> dict:
    """NAS → SD 덧붙이기 미러. 반환: {status, files_sent, bytes_sent, duration_sec}"""
    t0 = time.time()

    # ── M1: 저장소 계약 (특히 I1 — 심링크가 PRIMARY 를 가리키는가) ──
    try:
        assert_storage(require_backup=True)
    except StorageContractError as exc:
        msg = f"저장소 계약 위반으로 미러 중단:\n{exc}"
        logger.error(f"[mirror] {msg}")
        _log_run("skipped", None, None, time.time() - t0, str(exc))
        try:
            from scripts.notify import notify_failure
            notify_failure("미러 중단 — 저장소 계약 위반", str(exc))
        except Exception:  # noqa: BLE001
            pass
        return {"status": "skipped", "message": str(exc)}

    # ── M3: 백업 여유 용량 ──
    free = _free_gb(BACKUP_ROOT)
    if free < FREE_STOP_GB:
        msg = f"SD 여유 {free:.1f}GB < {FREE_STOP_GB}GB — 미러 중단"
        logger.error(f"[mirror] {msg}")
        _log_run("failed", None, None, time.time() - t0, msg)
        try:
            from scripts.notify import notify_failure
            notify_failure("SD 백업 용량 부족", msg)
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "message": msg}
    if free < FREE_WARN_GB:
        logger.warning(f"[mirror] SD 여유 {free:.1f}GB — 부분 미러(최근 N년) 전환 검토 필요")

    # ── rsync (덧붙이기 전용: --delete 없음) ──
    cmd = ["rsync", "-a", "--stats"]
    if dry_run:
        cmd.append("--dry-run")
    for pat in EXCLUDES:
        cmd += ["--exclude", pat]
    # 소스는 심링크가 아닌 절대경로. 트레일링 슬래시로 디렉터리 내용을 매핑.
    cmd += [f"{PRIMARY_ROOT}/", f"{BACKUP_ROOT}/"]

    logger.info(f"[mirror] {'(dry-run) ' if dry_run else ''}{PRIMARY_ROOT} → {BACKUP_ROOT}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dur = time.time() - t0

    if proc.returncode != 0:
        msg = f"rsync rc={proc.returncode}: {proc.stderr[:500]}"
        logger.error(f"[mirror] {msg}")
        _log_run("failed", None, None, dur, msg)
        try:
            from scripts.notify import notify_failure
            notify_failure("미러 실패", msg)
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "message": msg}

    files_sent, bytes_sent = _parse_stats(proc.stdout)
    logger.success(f"[mirror] 완료 — 전송 {files_sent:,}개 · "
                   f"{(bytes_sent or 0) / 1024 ** 2:.1f}MB · {dur:.0f}s")
    if not dry_run:
        _log_run("success", files_sent, bytes_sent, dur, "")
    return {"status": "success", "files_sent": files_sent,
            "bytes_sent": bytes_sent, "duration_sec": dur}


def _parse_stats(out: str) -> tuple[int, int]:
    """rsync --stats 출력에서 전송 파일 수·바이트."""
    files = total = 0
    for line in out.splitlines():
        if line.startswith("Number of regular files transferred:"):
            files = int(line.split(":")[1].strip().replace(",", ""))
        elif line.startswith("Total transferred file size:"):
            total = int(line.split(":")[1].strip().split()[0].replace(",", ""))
    return files, total


def check_freshness(warn_days: int = 7, error_days: int = 30) -> dict:
    """미러 신선도(§5.4) — `--delete` 를 뺀 대가로 '백업이 조용히 낡는' 리스크가 생겼다.

    SD 가 며칠 미마운트여도 데일리 수집은 계속되므로(미러만 실패), 이 검사가 없으면
    낡은 백업을 가진 채 모르고 지나간다.
    """
    with get_session() as s:
        last = s.execute(text(
            "SELECT max(finished_at) FROM storage_sync_log WHERE status='success'"
        )).scalar()
    if last is None:
        return {"ok": False, "days": None, "message": "성공한 미러 이력이 없다"}
    days = (datetime.utcnow() - last).days
    if days >= error_days:
        msg = f"SD 미러가 {days}일째 갱신되지 않았다(마지막 {last:%Y-%m-%d})"
        logger.error(f"[mirror] {msg}")
        try:
            from scripts.notify import notify_failure
            notify_failure("SD 백업이 낡음", msg)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "days": days, "message": msg}
    if days >= warn_days:
        logger.warning(f"[mirror] 마지막 성공 미러 {days}일 전({last:%Y-%m-%d})")
        return {"ok": True, "days": days, "message": "경고"}
    return {"ok": True, "days": days, "message": ""}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="전송 대상만 확인(파일 변경 없음)")
    ap.add_argument("--check-freshness", action="store_true",
                    help="미러 신선도만 검사하고 종료")
    args = ap.parse_args()

    if args.check_freshness:
        r = check_freshness()
        print(f"신선도: {'OK' if r['ok'] else 'STALE'} · {r['days']}일 전 · {r['message']}")
        sys.exit(0 if r["ok"] else 1)

    r = run_mirror(dry_run=args.dry_run)
    sys.exit(0 if r["status"] == "success" else 1)


if __name__ == "__main__":
    main()
