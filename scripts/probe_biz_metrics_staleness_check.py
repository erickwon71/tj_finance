"""Ad-hoc check: is the biz_metrics/biz_metrics mismatch found by
probe_biz_layer3_rewire_parity.py caused by Phase3 rewiring, or by the *existing* `biz_metrics`
table being stale relative to current `fin2/extract/sales_section.py` code?

Re-runs the OLD file-read path (`fin2.extract.biz_section.parse_biz_metrics`, unchanged code)
fresh from disk for one flagged filing and compares its metric_rows against both the DB baseline
and the new DB-only reconstruction. Read-only, no DB writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import parse_biz_metrics

CORP = "00120021"
FY = 2019

with get_session() as s:
    f = s.execute(text(
        "SELECT f.rcept_no, dt.file_path FROM filings f "
        "JOIN download_tasks dt ON dt.rcept_no=f.rcept_no "
        "WHERE f.corp_code=:c AND f.fiscal_year=:y AND f.report_type='annual' "
        "AND dt.status='completed' AND dt.file_type='xml' "
        "ORDER BY f.filed_at ASC LIMIT 1"), {"c": CORP, "y": FY}).fetchone()
    print("filing:", f)

    db_rows = s.execute(text(
        "SELECT table_ord, metric, narrative, grid FROM biz_section_tables "
        "WHERE rcept_no=:r AND table_ord=30"), {"r": f.rcept_no}).fetchall()
    print("biz_section_tables table_ord=30:", [(r.table_ord, r.metric, (r.narrative or '')[:60]) for r in db_rows])

    base = s.execute(text(
        "SELECT * FROM biz_metrics WHERE corp_code=:c AND fiscal_year=:y AND table_ord=30"),
        {"c": CORP, "y": FY}).fetchall()
    print(f"\nbaseline biz_metrics rows (table_ord=30, {len(base)}건):")
    for r in base:
        print(" ", dict(r._mapping))

sec_rows, met_rows = parse_biz_metrics(Path(f.file_path), CORP, FY)
fresh30 = [m for m in met_rows if m["table_ord"] == 30]
print(f"\n원문 재파싱(구코드 parse_biz_metrics) table_ord=30 결과({len(fresh30)}건):")
for m in fresh30:
    print(" ", m)
