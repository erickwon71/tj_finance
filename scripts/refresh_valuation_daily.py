"""A4a · valuation_daily materialized view refresh.

`collector/db.py`'s migrations create `valuation_daily` as a materialized view
`WITH NO DATA` (avoids a long-running refresh blocking DB bootstrap). This
script does the actual (re)population:

- First run ever: plain `REFRESH MATERIALIZED VIEW` (matview has no data yet;
  `CONCURRENTLY` requires existing data to diff against).
- Every run after that: `REFRESH MATERIALIZED VIEW CONCURRENTLY` (needs the
  unique index `ux_valuation_daily_corp_date`, already created by the
  migration) so reads against `valuation_daily` are never blocked while it
  refreshes.

usage:
  python scripts/refresh_valuation_daily.py           # first-time full populate (run once, manually)
  python scripts/refresh_valuation_daily.py --concurrent  # subsequent refreshes (called from collect_new.py)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import engine


def refresh(concurrent: bool) -> None:
    sql = "REFRESH MATERIALIZED VIEW CONCURRENTLY valuation_daily" if concurrent \
        else "REFRESH MATERIALIZED VIEW valuation_daily"
    t0 = time.monotonic()
    logger.info(f"[refresh] {sql} 시작...")
    with engine.begin() as conn:
        conn.execute(text(sql))
        count = conn.execute(text("SELECT count(*) FROM valuation_daily")).scalar()
    logger.success(f"[refresh] 완료 — {count:,}행, {time.monotonic() - t0:,.1f}초")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrent", action="store_true",
                     help="REFRESH CONCURRENTLY 사용(최초 적재 이후에만 가능 — 데이터가 이미 있어야 함)")
    args = ap.parse_args()
    refresh(args.concurrent)


if __name__ == "__main__":
    main()
