"""R348: rebuild biz_metrics / biz_metrics_periodic for the (corp, year, report_type) groups listed
by r348_sales_affected.py. Layer 3 only (reads biz_section_tables).

usage: python scripts/qa/r348_sales_rebuild.py <affected.csv> --shard 0/4
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loguru import logger  # noqa: E402

from collector.biz_metrics import sync_biz_metrics_corp  # noqa: E402
from collector.biz_metrics_periodic import sync_biz_metrics_periodic_corp  # noqa: E402
from collector.db import get_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args()
    i, n = (int(x) for x in a.shard.split("/"))
    with open(a.csv) as fh:
        groups = [(r["corp_code"], int(r["fiscal_year"]), r["report_type"]) for r in csv.DictReader(fh)]
    # one call per (corp, year, annual|periodic); periodic sync covers quarter + half together
    todo = sorted({(c, y, "annual" if t == "annual" else "periodic") for c, y, t in groups
                   if int(c) % n == i})
    logger.info(f"[r348] {len(todo)} groups (shard {a.shard})")
    agg = {"ok": 0, "err": 0}
    for k, (corp, year, kind) in enumerate(todo, 1):
        try:
            with get_session() as s:
                if kind == "annual":
                    sync_biz_metrics_corp(s, corp, year)
                else:
                    sync_biz_metrics_periodic_corp(s, corp, year, year_min=2015)
                s.commit()
            agg["ok"] += 1
        except Exception as exc:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[r348] {corp} {year} {kind} failed: {type(exc).__name__}: {exc}")
        if k % 200 == 0 or k == len(todo):
            logger.info(f"[r348] {k}/{len(todo)} {agg}")
    print(agg)


if __name__ == "__main__":
    main()
