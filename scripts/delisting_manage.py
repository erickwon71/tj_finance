"""상장폐지 판정·아카이브 관리 CLI.

계획: docs/plans/collection_pipeline_restore_2026-07-31.md §6.4·§6.4b·§6.6.2

**드라이런이 기본이다.** 원문 이동·SD 삭제는 명시적 `--apply` 에서만 일어난다.
그리고 결정 D1 에 따라 **원문은 절대 삭제하지 않는다** — NAS 아카이브로 옮겨 영구 보존한다.
(SD 백업 폴더는 지운다. 아카이브에 실물이 확인된 뒤에만.)

★ 2026-08-01 부터 이관·SD 정리는 **데일리가 자동으로** 한다(collect_new.py ⓪-4).
  실제 동작은 전부 `collector/delisting_archive.py` 에 있고 여기는 수동 진입점이다.
  손으로 쓸 일은 드라이런 확인·오탐 복원·상한(A1)에 걸려 멈춘 백로그 해소 정도.

사용:
    python scripts/delisting_manage.py --evaluate            # 판정 드라이런
    python scripts/delisting_manage.py --evaluate --apply    # 판정 DB 반영
    python scripts/delisting_manage.py --list                # 현재 상태 일람
    python scripts/delisting_manage.py --archive             # 확정분 원문 이관(드라이런)
    python scripts/delisting_manage.py --archive --apply
    python scripts/delisting_manage.py --restore 00172291    # 되돌리기
    python scripts/delisting_manage.py --sync-backup         # SD 정리(드라이런)
    python scripts/delisting_manage.py --sync-backup --apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.delisting_archive import (
    MAX_ARCHIVE_PER_RUN, archive_confirmed, purge_backup,
)
from collector.storage_guard import PRIMARY_ROOT, assert_storage


def cmd_evaluate(apply: bool) -> int:
    from collector import krx_client as kc
    from collector.corp_collector import _get_krx_universe
    from collector.delisting import evaluate

    # 판정 소스는 **KRX 원본 목록 전 증권**이다. 투자 유니버스(보통주만)를 쓰면
    # 거래소에 멀쩡히 상장된 인프라펀드·리츠가 상장폐지로 오판된다.
    universe, market_status = _get_krx_universe()
    _, results = kc.fetch_all()
    listed = kc.listed_codes(list(results.values()))
    if not listed and universe:
        # KRX 가 죽고 FDR 로 폴백한 경우 — FDR 목록에는 우선주가 섞여 있어 상장 여부
        # 판정에는 오히려 적합하다(필터 전 목록).
        listed = set(universe)
    # 상장폐지 명부 — 폐지일·사유가 명시된 양성 증거(부재 추론보다 강하다).
    registry = kc.fetch_delisted()
    print(f"상장 종목(전 증권) {len(listed):,}개 · 폐지 명부 {len(registry):,}건 기준으로 판정\n")

    result = evaluate(listed, market_status, krx_mode=universe is not None,
                      apply=apply, delisted_registry=registry)

    if result["skipped"]:
        print(f"\n판정 스킵 — {result['reason']}")
        return 1

    for v in sorted(result["verdicts"], key=lambda x: (x.status, x.corp_name)):
        mark = {"confirmed": "★", "candidate": "·", "reinstated": "↩", "hold": " "}[v.status]
        print(f" {mark} {v.status:11s} {v.corp_code} {v.corp_name}")
        print(f"       {v.reason}")
        for sig in v.signals:
            print(f"       └ {sig}")
    c = result["counts"]
    print(f"\n후보 {c['candidate']} · 확정 {c['confirmed']} · 복귀 {c['reinstated']} · "
          f"보류 {c['hold']}{'' if apply else '   (드라이런 — DB 미반영)'}")
    return 0


def cmd_list() -> int:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, corp_name, stock_code, market, is_active,
                   delisting_status, delisting_first_seen, delisted_at, archive_path
            FROM corporations
            WHERE delisting_status IS NOT NULL OR is_active = FALSE
            ORDER BY delisting_status NULLS LAST, corp_name
        """)).fetchall()
    if not rows:
        print("상장폐지 상태가 기록된 기업 없음.")
        return 0
    print(f"{'코드':9s} {'종목':7s} {'상태':11s} {'최초부재':11s} {'확정일':11s} 기업명")
    for r in rows:
        print(f"{r[0]:9s} {r[2] or '-':7s} {r[5] or '(없음)':11s} "
              f"{str(r[6] or '-'):11s} {str(r[7] or '-'):11s} {r[1]}"
              f"{'  [아카이브됨]' if r[8] else ''}")
    return 0


def cmd_archive(apply: bool) -> int:
    """확정분 원문을 NAS 아카이브로 **이동**(삭제 아님, 결정 D1)."""
    r = archive_confirmed(apply=apply)
    if not r["pending"]:
        print("아카이브 대상 없음(확정이면서 미이관인 기업).")
        return 0
    if r["capped"]:
        print(f"! 이관 대상 {r['pending']}개 > 상한 {MAX_ARCHIVE_PER_RUN}개 — 중단.\n"
              f"  판정이 비정상적으로 쌓였는지 --list 로 먼저 확인할 것.")
        return 1
    for corp_code, corp_name, dst, mb in r["moved"]:
        print(f"  {'이동' if apply else '(드라이런)'} {corp_code} {corp_name} → {dst}  ({mb:.0f}MB)")
    for corp_code, corp_name in r["no_source"]:
        print(f"  - {corp_code} {corp_name}: 원문 폴더 없음 — 건너뜀")
    for corp_code, corp_name, msg in r["errors"]:
        print(f"  ! {corp_code} {corp_name}: {msg}")

    print(f"\n{'이관 완료' if apply else '드라이런'} — 대상 {r['pending']}개")
    if apply:
        print(f"이동 {len(r['moved'])}개 · 원문없음 {len(r['no_source'])}개 · 실패 {len(r['errors'])}개")
        print("SD 백업 정리는 데일리(⓪-4)가 이어서 한다. 지금 하려면 --sync-backup --apply.")
    return 1 if r["errors"] else 0


def cmd_restore(corp_code: str, apply: bool) -> int:
    """오탐 되돌리기 — 아카이브에서 원위치 + 상태 해제."""
    assert_storage(require_backup=False)
    with get_session() as s:
        row = s.execute(text("""
            SELECT corp_name, market, archive_path, delisting_status
            FROM corporations WHERE corp_code = :c
        """), {"c": corp_code}).fetchone()
    if row is None:
        print(f"{corp_code}: 기업을 찾을 수 없다.")
        return 1
    corp_name, market, archive_path, status = row
    print(f"{corp_code} {corp_name} — 상태 {status} · 아카이브 {archive_path or '(없음)'}")

    if archive_path:
        src = Path(archive_path)
        dst = PRIMARY_ROOT / (market or "") / src.name
        print(f"  {'복원' if apply else '(드라이런)'} {src} → {dst}")
        if apply and src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    if apply:
        with get_session() as s:
            s.execute(text("""
                UPDATE corporations
                SET delisting_status = 'reinstated', delisted_at = NULL,
                    delisting_first_seen = NULL, archive_path = NULL,
                    is_active = TRUE, updated_at = now()
                WHERE corp_code = :c
            """), {"c": corp_code})
            s.commit()
        print("  상태 → reinstated · is_active=TRUE")
    else:
        print("  (드라이런 — DB 미반영)")
    return 0


def cmd_sync_backup(apply: bool) -> int:
    """SD 백업에서 아카이브된 기업 폴더를 제거한다(§6.4b).

    데일리 미러는 덧붙이기 전용이라 아카이브 이관분이 SD 에 그대로 남는다. 정리하되
    **전역 `rsync --delete` 를 쓰지 않는다** — 확정+아카이브 실재(파일 수 포함)가 확인된
    폴더 목록만 지운다. 2026-08-01 부터 데일리 ⓪-4 가 같은 함수를 자동으로 돌린다.
    """
    r = purge_backup(apply=apply)
    for corp_code, corp_name, sd_dir, mb in r["purged"]:
        print(f"  {'삭제' if apply else '(드라이런)'} {corp_code} {corp_name} {sd_dir}  ({mb:.0f}MB)")
    for corp_code, corp_name, reason in r["skipped"]:
        print(f"  ! {corp_code} {corp_name}: {reason} — 제외")
    for corp_code, corp_name, msg in r["errors"]:
        print(f"  ! {corp_code} {corp_name}: {msg}")
    if not r["purged"] and not r["skipped"]:
        print("SD 정리 대상 없음.")
        return 0
    print(f"\n{'삭제 완료' if apply else '드라이런'} — "
          f"{len(r['purged'])}개 폴더 · {r['mb']:.0f}MB · 제외 {len(r['skipped'])}개")
    return 1 if r["errors"] else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--evaluate", action="store_true", help="상장폐지 판정 실행")
    g.add_argument("--list", action="store_true", help="현재 상태 일람")
    g.add_argument("--archive", action="store_true", help="확정분 원문을 NAS 아카이브로 이관")
    g.add_argument("--restore", type=str, metavar="CORP_CODE", help="오탐 되돌리기")
    g.add_argument("--sync-backup", action="store_true", help="SD 백업에서 아카이브분 제거")
    ap.add_argument("--apply", action="store_true",
                    help="실제 반영(미지정 = 드라이런). 원문 삭제는 어떤 경우에도 하지 않는다")
    args = ap.parse_args()

    if args.evaluate:
        sys.exit(cmd_evaluate(args.apply))
    if args.list:
        sys.exit(cmd_list())
    if args.archive:
        sys.exit(cmd_archive(args.apply))
    if args.restore:
        sys.exit(cmd_restore(args.restore, args.apply))
    if args.sync_backup:
        sys.exit(cmd_sync_backup(args.apply))


if __name__ == "__main__":
    main()
