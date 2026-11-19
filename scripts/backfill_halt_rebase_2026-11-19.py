"""R351 one-off: re-fetch stocks whose halt days are off their neighbours' basis (last N days).

Same per-stock path as the nightly ①-c (analyzer.adjusted_history.refetch_stock logic): existing
dates only, OHLC only, rolled back when traded-day or halt-day boundaries increase.
--dry-run applies the plan inside a transaction and always rolls back, reporting what would change.

usage:
    python scripts/backfill_halt_rebase_2026-11-19.py --since-days 400 --dry-run
    python scripts/backfill_halt_rebase_2026-11-19.py --since-days 400
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

from analyzer.adjusted_history import _UPDATE, halt_boundaries, plan_rows, stale_boundaries  # noqa: E402
from analyzer.price_fetcher import fetch_naver_daily  # noqa: E402
from collector.db import get_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.4)
    a = ap.parse_args()
    today = date.today()
    with get_session() as s:
        codes = sorted({h[0] for h in halt_boundaries(s, since=today - timedelta(days=a.since_days))})
    logger.info(f"[r351] {len(codes)} stocks flagged (dry_run={a.dry_run})")
    c = Counter()
    for i, code in enumerate(codes, 1):
        fetched = fetch_naver_daily(code, "19900101", today.strftime("%Y%m%d"))
        if not fetched:
            c["no_source"] += 1
            continue
        with get_session() as s:
            old = {r[0]: {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "close_raw": r[5]}
                   for r in s.execute(text(
                       "SELECT trade_date, open_price, high_price, low_price, close_price, close_raw "
                       "FROM stock_prices WHERE stock_code = :c"), {"c": code})}
            sb, hb = len(stale_boundaries(s, codes=[code])), len(halt_boundaries(s, codes=[code]))
            rows = plan_rows(old, fetched)
            if not rows:
                c["unchanged"] += 1
                continue
            s.execute(text(_UPDATE), [{"code": code, **r} for r in rows])
            sa, ha = len(stale_boundaries(s, codes=[code])), len(halt_boundaries(s, codes=[code]))
            c["halt_before"] += hb
            c["halt_after"] += ha
            c["rows"] += len(rows)
            if sa > sb or ha > hb:
                s.rollback()
                c["rolled_back"] += 1
                logger.warning(f"[r351] {code}: stale {sb}->{sa} halt {hb}->{ha}, rolled back")
                continue
            if a.dry_run:
                s.rollback()
            else:
                s.commit()
            c["updated" if not a.dry_run else "would_update"] += 1
        if i % 50 == 0:
            logger.info(f"[r351] {i}/{len(codes)} {dict(c)}")
        time.sleep(a.sleep)
    print(dict(c))


if __name__ == "__main__":
    main()
