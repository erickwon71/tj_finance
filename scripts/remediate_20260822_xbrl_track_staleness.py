"""Remediation (2026-08-22): re-sync report_lines for filings that were first ingested
via the XBRL-instance zip fallback (`unit_source='xbrl'`) but later got a proper
document.xml (Track A) available on disk — the note_lines_sync.py `_LOADED_SQL` guard
didn't know that and treated them as "already loaded", so the stale xbrl_zip values
were never overwritten. Fix is in collector/note_lines_sync.py (unit_source guard);
this script is the one-time backfill for the ~1,841 filings / ~1,767 corps affected
by the 2026-08 half-report [014] outage (see scripts/redownload_202608_xbrl_zip_bulk.py
for the matching downloader-side incident).

Usage:
    python scripts/remediate_20260822_xbrl_track_staleness.py --dry-run
    python scripts/remediate_20260822_xbrl_track_staleness.py --corps 00580667
    python scripts/remediate_20260822_xbrl_track_staleness.py --all
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from loguru import logger  # noqa: E402

from collector.db import get_session  # noqa: E402

_AFFECTED_CORPS_SQL = text(
    """
    SELECT DISTINCT f.corp_code
    FROM report_lines rl
    JOIN download_tasks dt ON dt.rcept_no = rl.rcept_no
    JOIN filings f ON f.rcept_no = rl.rcept_no
    WHERE rl.unit_source = 'xbrl'
      AND dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
    ORDER BY 1
    """
)


def get_affected_corps() -> list[str]:
    with get_session() as session:
        return session.execute(_AFFECTED_CORPS_SQL).scalars().all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="쉼표구분 corp_code (지정 시 그것만, 테스트용)")
    ap.add_argument("--all", action="store_true", help="영향받는 전체 corp")
    ap.add_argument("--dry-run", action="store_true", help="대상 목록만 출력")
    ap.add_argument("--year-min", type=int, default=2026,
                     help="sync_layer2_lines 의 fiscal_year 하한(기본 2026 — 이 인시던트는 "
                          "전부 2026-08 필링이라, 기본 1999 로 두면 corp당 전체 이력을 "
                          "재스캔하는 낭비가 생긴다)")
    args = ap.parse_args()

    affected = get_affected_corps()
    logger.info(f"[remediate] 영향받는 corp 수: {len(affected)}")

    if args.dry_run:
        print(f"영향받는 corp 수: {len(affected)}")
        print(affected[:20], "..." if len(affected) > 20 else "")
        return

    if args.corps:
        targets = [c.strip() for c in args.corps.split(",")]
    elif args.all:
        targets = affected
    else:
        print("--corps 또는 --all 중 하나를 지정하세요 (또는 --dry-run)")
        return

    from collector.note_lines_sync import sync_layer2_lines
    batch_size = 25
    total = {"corps": 0, "filings": 0, "rows": 0, "body_rows": 0, "errors": 0}
    n_batches = -(-len(targets) // batch_size)
    for i in range(0, len(targets), batch_size):
        batch = targets[i:i + batch_size]
        res = sync_layer2_lines(corps=batch, year_min=args.year_min, recheck=False)
        for k in total:
            total[k] += res.get(k, 0)
        logger.info(
            f"[remediate] 배치 {i // batch_size + 1}/{n_batches} 완료 — {res} "
            f"(누적: {total})"
        )
    print(total)


if __name__ == "__main__":
    main()
