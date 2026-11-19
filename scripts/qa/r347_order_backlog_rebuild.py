"""R347 retroactive rebuild of order_backlog + order_backlog_periodic (layer 3 only).

Reads biz_section_tables (layer 2) through the normal sync functions; raw files are opened only
when a filing's layer-2 grid is missing (ensure_biz_raw_tables), as in the daily pipeline.

usage:
    python scripts/qa/r347_order_backlog_rebuild.py --shard 0/4
    python scripts/qa/r347_order_backlog_rebuild.py --corps 00406046
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

from collector.biz_metrics_periodic import sync_order_backlog_periodic_corp  # noqa: E402
from collector.db import get_session  # noqa: E402
from collector.order_backlog import sync_order_backlog_corp  # noqa: E402


def _corps(args) -> list[str]:
    if args.corps:
        return [c.strip() for c in args.corps.split(",") if c.strip()]
    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT corp_code FROM biz_section_tables WHERE domain='order_backlog' "
            "UNION SELECT corp_code FROM order_backlog "
            "UNION SELECT corp_code FROM order_backlog_periodic ORDER BY 1")).fetchall()]
    i, n = (int(x) for x in args.shard.split("/"))
    return [c for c in corps if int(c) % n == i]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps")
    ap.add_argument("--shard", default="0/1")
    args = ap.parse_args()
    corps = _corps(args)
    logger.info(f"[r347] {len(corps)} corps (shard {args.shard})")
    agg = {"corps": 0, "err": 0, "rows": 0, "rows_p": 0}
    for k, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                a = sync_order_backlog_corp(s, corp)
                # periodic tables are loaded for 2015+ only (backfill_biz_periodic.py --year-min 2015)
                p = sync_order_backlog_periodic_corp(s, corp, year_min=2015)
                s.commit()
            agg["rows"] += a["rows"]
            agg["rows_p"] += p["rows"]
            agg["corps"] += 1
        except Exception as exc:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[r347] {corp} failed: {type(exc).__name__}: {exc}")
        if k % 100 == 0 or k == len(corps):
            logger.info(f"[r347] {k}/{len(corps)} {agg}")
    print(agg)


if __name__ == "__main__":
    main()
