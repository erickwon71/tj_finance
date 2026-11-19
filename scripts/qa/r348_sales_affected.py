"""R348/R349: list (corp_code, fiscal_year, report_type) whose sales tables map differently
from the given old mapper (git HEAD before R348) — compares value, period and unit. Writes a CSV.

usage: python scripts/qa/r348_sales_affected.py <old_sales_section.py> <out.csv>
"""
import csv
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract import sales_section as new  # noqa: E402

spec = importlib.util.spec_from_file_location("ss_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
sys.modules["ss_old"] = old
spec.loader.exec_module(old)

out = set()
with get_session() as s:
    q = s.execute(text(
        "SELECT t.corp_code, t.fiscal_year, f.report_type, t.narrative, t.grid FROM biz_section_tables t "
        "JOIN filings f USING (rcept_no) WHERE t.domain='sales'"))
    for corp, fy, rt, nar, g in q:
        o = old.map_sales_table(old.SalesTable(narrative=nar or "", grid=g), fy)
        n = new.map_sales_table(new.SalesTable(narrative=nar or "", grid=g), fy)
        if [(r.segment, r.item, r.channel, r.value, r.period_year, r.period_label, r.unit) for r in o] != \
           [(r.segment, r.item, r.channel, r.value, r.period_year, r.period_label, r.unit) for r in n]:
            out.add((corp, fy, rt))
with open(sys.argv[2], "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["corp_code", "fiscal_year", "report_type"])
    w.writerows(sorted(out))
print(len(out), "corp-year-type groups;", len({c for c, _, _ in out}), "corps")
