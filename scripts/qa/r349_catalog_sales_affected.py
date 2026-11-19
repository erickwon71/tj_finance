"""R349: (corp_code, fiscal_year, report_type) whose catalog 'sales' tables map differently from
the given old biz_catalog module (git HEAD before R349). Appends to / writes a CSV.

usage: python scripts/qa/r349_catalog_sales_affected.py <old_biz_catalog.py> <out.csv>
"""
import csv
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from collector.biz_metrics import _CATALOG_NARRATIVE_RE  # noqa: E402
from collector.db import get_session  # noqa: E402
from fin2.extract import biz_catalog as new  # noqa: E402

spec = importlib.util.spec_from_file_location("bc_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
sys.modules["bc_old"] = old
spec.loader.exec_module(old)


def _ct(mod, narrative, grid):
    m = _CATALOG_NARRATIVE_RE.match(narrative or "")
    if m:
        return mod.CaptionedTable(subsection=m.group("subsection"), caption="",
                                  caption_raw=m.group("caption_raw"), narrative=m.group("narrative"),
                                  grid=grid, inherited=bool(m.group("inherited")))
    return mod.CaptionedTable(subsection="", caption="", caption_raw="", narrative=narrative or "",
                              grid=grid, inherited=False)


def _key(rows):
    return [(r.segment, r.item, r.period_label, r.period_year, r.value, r.unit) for r in rows]


out = set()
with get_session() as s:
    q = s.execute(text(
        "SELECT t.corp_code, t.fiscal_year, f.report_type, t.narrative, t.grid FROM biz_section_tables t "
        "JOIN filings f USING (rcept_no) WHERE t.domain='catalog' AND t.metric='sales'"))
    for corp, fy, rt, nar, g in q:
        o = old.map_catalog_table(_ct(old, nar, g), "sales", fy)
        n = new.map_catalog_table(_ct(new, nar, g), "sales", fy)
        if _key(o) != _key(n):
            out.add((corp, fy, rt))
with open(sys.argv[2], "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["corp_code", "fiscal_year", "report_type"])
    w.writerows(sorted(out))
print(len(out), "corp-year-type groups;", len({c for c, _, _ in out}), "corps")
