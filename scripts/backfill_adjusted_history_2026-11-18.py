"""R338 one-off: re-base the adjusted price history of every active stock (plan A).

Plan: docs/plans/adjusted_price_full_history_plan_2026-11-18.md (A안).
Backup of the touched columns: public.stock_prices_ohlc_backup_20261118.
Each stock is fetched once from Naver siseJson (listing date to today) and rewritten in its own
transaction (analyzer.adjusted_history.refetch_stock: existing dates only, OHLC only, rolled back
when it would add stale boundaries). Results go to a JSONL file; --resume skips stocks already in it.

usage:
  python scripts/backfill_adjusted_history_2026-11-18.py --out logs/adjusted_history_backfill_2026-11-18.jsonl
  python scripts/backfill_adjusted_history_2026-11-18.py --out ... --resume
  python scripts/backfill_adjusted_history_2026-11-18.py --out ... --stocks 052400,340570
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from analyzer.adjusted_history import refetch_stock
from collector.db import get_session


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--stocks", help="comma-separated stock codes (default: every active stock)")
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    if args.stocks:
        codes = args.stocks.split(",")
    else:
        with get_session() as s:
            codes = [r[0] for r in s.execute(text(
                "SELECT DISTINCT stock_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
                "AND stock_code <> '' ORDER BY 1"))]
    out = Path(args.out)
    done = set()
    if args.resume and out.exists():
        done = {json.loads(line)["code"] for line in out.read_text().splitlines() if line.strip()}
    todo = [c for c in codes if c not in done]
    logger.info(f"[adj-backfill] {len(todo)} stocks ({len(done)} already done)")
    agg: Counter = Counter()
    with out.open("a", encoding="utf-8") as f:
        for i, code in enumerate(todo, 1):
            try:
                res = refetch_stock(code)
            except Exception as e:  # noqa: BLE001 - per-stock isolation
                res = {"code": code, "status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
            f.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
            f.flush()
            agg[res["status"]] += 1
            if i % 100 == 0 or i == len(todo):
                logger.info(f"  ..{i}/{len(todo)} {dict(agg)}")
            if args.sleep:
                time.sleep(args.sleep)
    logger.success(f"[adj-backfill] done {dict(agg)}")


if __name__ == "__main__":
    main()
