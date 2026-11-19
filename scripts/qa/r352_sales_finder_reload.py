"""R352: reload the filings whose sales tables change under the new finder.

Step 1 (layer 2): re-extract `biz_section_tables` for each listed rcept_no (delete-then-insert per
filing, same writer as the daily pipeline).
Step 2 (layer 3): rebuild biz_metrics / biz_metrics_periodic for every (corp, fiscal_year, kind)
touched. Quarter/half rebuilds keep the existing 2015+ range (year_min=2015, see R348 note).

usage: python scripts/qa/r352_sales_finder_reload.py <rcepts.csv> --shard 0/4 [--apply]
  rcepts.csv columns: rcept_no (other columns ignored). Without --apply only counts are printed.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

from collector.biz_metrics import sync_biz_metrics_corp  # noqa: E402
from collector.biz_metrics_periodic import sync_biz_metrics_periodic_corp  # noqa: E402
from collector.db import get_session  # noqa: E402
from fin2.layer2.biz_raw_tables import extract_biz_raw_tables, store_biz_raw_tables  # noqa: E402

_SD = "/Volumes/dart_data/raw_report"


def _resolve(fp: str) -> Path:
    """Read from the SD-card mirror when the file is there (bulk re-read; NAS is slow)."""
    k = fp.find("raw_report/")
    if k >= 0:
        sd = os.path.join(_SD, fp[k + len("raw_report/"):])
        if os.path.exists(sd):
            return Path(sd)
    return Path(fp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    i, n = (int(x) for x in a.shard.split("/"))
    with open(a.csv) as fh:
        rcepts = sorted({r["rcept_no"] for r in csv.DictReader(fh)})
    with get_session() as s:
        meta = s.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.report_type, dt.file_path
            FROM filings f JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE f.rcept_no = ANY(:r) AND dt.status = 'completed' AND dt.file_type = 'xml'
              AND dt.file_path IS NOT NULL"""), {"r": rcepts}).all()
    # shard by corp so two shards never rebuild the same (corp, year) in layer 3
    meta = [m for m in meta if int(m.corp_code) % n == i]
    groups = sorted({(m.corp_code, m.fiscal_year, "annual" if m.report_type == "annual" else "periodic")
                     for m in meta})
    logger.info(f"[r352] shard {a.shard}: {len(meta)} filings, {len(groups)} layer-3 groups")
    if not a.apply:
        return
    agg = {"l2_ok": 0, "l2_err": 0, "l3_ok": 0, "l3_err": 0}
    for k, m in enumerate(meta, 1):
        try:
            rows = extract_biz_raw_tables(_resolve(m.file_path), m.corp_code, m.fiscal_year, m.report_type)
            with get_session() as s:
                store_biz_raw_tables(s, m.rcept_no, rows)
                s.commit()
            agg["l2_ok"] += 1
        except Exception as exc:  # noqa: BLE001
            agg["l2_err"] += 1
            logger.warning(f"[r352] l2 {m.rcept_no} failed: {type(exc).__name__}: {exc}")
        if k % 500 == 0:
            logger.info(f"[r352] l2 {k}/{len(meta)} {agg}")
    for k, (corp, year, kind) in enumerate(groups, 1):
        try:
            with get_session() as s:
                if kind == "annual":
                    sync_biz_metrics_corp(s, corp, year)
                else:
                    sync_biz_metrics_periodic_corp(s, corp, year, year_min=2015)
                s.commit()
            agg["l3_ok"] += 1
        except Exception as exc:  # noqa: BLE001
            agg["l3_err"] += 1
            logger.warning(f"[r352] l3 {corp} {year} {kind} failed: {type(exc).__name__}: {exc}")
        if k % 500 == 0:
            logger.info(f"[r352] l3 {k}/{len(groups)} {agg}")
    print(agg)


if __name__ == "__main__":
    main()
