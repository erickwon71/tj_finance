"""Backfill layer-2 lines for every filing downloaded as an XBRL instance zip.

Why this exists (2026-08-18):
  `collect_new.py --standardize-only` drives ④-4 (`sync_xbrl_instance_lines`) with the
  corp list from `app/data/collect.py::needs_standardize_corps()`, which selects on
  `download_tasks.file_type='xml'`. Filings that fell back to the XBRL instance zip
  (`_try_xbrl_instance_fallback()`, OpenDART [014]) have `file_type='xbrl_zip'` and are
  therefore invisible to that selector.

  Measured 2026-08-18: of the 2,628 filings received in 2026-08, 1,845 are xbrl_zip-only
  (every prior month in 2026 was ~100% xml). 1,765 corps have untranscribed zips; only
  835 of them are reachable via needs_standardize_corps() — and only incidentally,
  because they happen to have unrelated pre-2008 gaps. 930 corps are unreachable.

This driver selects targets by the same predicate the sync function itself uses, so it
covers exactly the population that pipeline can load, with no corp-list dependency.

Idempotent and resumable: pending targets are recomputed on every run, and each batch
commits separately (`sync_xbrl_instance_lines` commits per call), so an interrupted run
is continued by simply re-running.

NOTE: this is a one-off backfill, not a pipeline change. The durable fix — teaching the
daily pipeline's two call sites about xbrl_zip-pending corps — is a separate decision
(docs/runbook_new_parser_pipeline_integration.md).

Usage:
  .venv/bin/python scripts/backfill_xbrl_instance_lines_2026-08-18.py --dry-run
  .venv/bin/python scripts/backfill_xbrl_instance_lines_2026-08-18.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.xbrl_instance_lines_sync import FY_MIN, sync_xbrl_instance_lines

# Mirrors _TARGETS_SQL / _LOADED_SQL in collector/xbrl_instance_lines_sync.py, but scoped
# to "which corps still have work" rather than "which filings to load for these corps".
_PENDING_CORPS_SQL = text(
    """
    SELECT f.corp_code, count(*) AS pending_filings
    FROM download_tasks dt JOIN filings f USING(rcept_no)
    WHERE dt.status = 'completed'
      AND dt.file_type = 'xbrl_zip'
      AND dt.file_path IS NOT NULL
      AND f.fiscal_year >= :fy_min
      AND NOT EXISTS (
        SELECT 1 FROM report_lines r
        WHERE r.rcept_no = dt.rcept_no AND r.unit_source = 'xbrl')
    GROUP BY f.corp_code
    ORDER BY f.corp_code
    """
)


def pending_corps(year_min: int) -> list[tuple[str, int]]:
    with get_session() as session:
        rows = session.execute(_PENDING_CORPS_SQL, {"fy_min": year_min}).fetchall()
    return [(r[0], r[1]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year-min", type=int, default=FY_MIN,
                    help=f"이 회계연도 이상만 (기본 {FY_MIN} — sync 함수 기본값과 동일)")
    ap.add_argument("--batch-size", type=int, default=25,
                    help="한 번의 sync 호출에 넘길 기업 수. 배치마다 커밋된다")
    ap.add_argument("--limit", type=int, default=None,
                    help="처리할 기업 수 상한(시험용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="대상만 집계하고 적재하지 않는다")
    args = ap.parse_args()

    targets = pending_corps(args.year_min)
    total_filings = sum(n for _, n in targets)
    logger.info(f"[backfill-xbrl] 대상 기업 {len(targets):,} · 미적재 필링 {total_filings:,} "
                f"(fy >= {args.year_min})")

    if args.limit:
        targets = targets[: args.limit]
        logger.info(f"[backfill-xbrl] --limit 적용 — 기업 {len(targets):,}")

    if args.dry_run:
        logger.info("[backfill-xbrl] --dry-run — 적재하지 않고 종료")
        return

    corps = [c for c, _ in targets]
    agg = {"corps": 0, "filings": 0, "rows": 0, "table_rows": 0, "errors": 0}
    t0 = time.time()

    for i in range(0, len(corps), args.batch_size):
        batch = corps[i : i + args.batch_size]
        try:
            r = sync_xbrl_instance_lines(batch, year_min=args.year_min)
        except Exception as exc:  # noqa: BLE001 — one batch must not kill the run
            agg["errors"] += 1
            logger.error(f"[backfill-xbrl] 배치 실패({batch[0]}~{batch[-1]}): "
                         f"{type(exc).__name__}: {exc}")
            continue
        for k in agg:
            agg[k] += r.get(k, 0)
        done = min(i + args.batch_size, len(corps))
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed else 0
        eta = (len(corps) - done) / rate if rate else 0
        logger.info(f"[backfill-xbrl]   진행 {done:,}/{len(corps):,} "
                    f"(필링 {agg['filings']:,} · 본문 {agg['rows']:,}행 · "
                    f"오류 {agg['errors']}) — 경과 {elapsed/60:.1f}분 · 잔여 ~{eta/60:.1f}분")

    logger.success(f"[backfill-xbrl] 완료 — 기업 {agg['corps']:,} · 필링 {agg['filings']:,} · "
                   f"본문 {agg['rows']:,}행 · 표 {agg['table_rows']:,} · 오류 {agg['errors']} "
                   f"· {(time.time()-t0)/60:.1f}분")

    left = pending_corps(args.year_min)
    logger.info(f"[backfill-xbrl] 잔여 대상 기업 {len(left):,} · 필링 "
                f"{sum(n for _, n in left):,}")


if __name__ == "__main__":
    main()
