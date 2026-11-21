"""R366: (corp, fiscal_year, report_type) groups to rebuild in layer 3 (biz_metrics/_periodic).

1. filings whose layer-2 biz tables were re-read (r366_biz_layer2_reread.py --write output, status
   'changed');
2. production/sales/catalog tables whose mapping changes with R366 (wrapped numbers joined, no row
   from stacked cells) — mapper off vs on over the stored grids.

usage: python scripts/qa/r366_affected_groups.py <reread_write.csv> <out.csv>
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2  # noqa: E402

from collector.biz_metrics import _map_row  # noqa: E402
from fin2.extract import biz_section  # noqa: E402


def main() -> None:
    reread_csv, out_csv = sys.argv[1], sys.argv[2]
    with open(reread_csv) as fh:
        reread = [r["rcept_no"] for r in csv.DictReader(fh) if r["status"] == "changed"]
    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor()
    groups = set()
    cur.execute("SELECT corp_code, fiscal_year, report_type FROM filings WHERE rcept_no = ANY(%s)", (reread,))
    groups |= {tuple(r) for r in cur.fetchall()}
    n_reread = len(groups)
    c2 = conn.cursor(name="c")
    c2.itersize = 2000
    c2.execute("SELECT b.domain, b.metric, b.narrative, b.grid, b.fiscal_year, f.corp_code, f.report_type "
               "FROM biz_section_tables b JOIN filings f USING (rcept_no) "
               "WHERE b.domain IN ('production','sales','catalog') AND b.grid::text LIKE '%\\\\n%'")
    for dom, met, nar, grid, fy, corp, rtype in c2:
        biz_section._R366_STACKED_ROWS = False
        try:
            a = _map_row(dom, met, nar, grid, fy)
        except Exception:  # noqa: BLE001
            continue
        biz_section._R366_STACKED_ROWS = True
        if a != _map_row(dom, met, nar, grid, fy):
            groups.add((corp, fy, rtype))
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corp_code", "fiscal_year", "report_type"])
        for g in sorted(groups):
            w.writerow(g)
    print(f"groups {len(groups)} (from re-read {n_reread}), corps {len({g[0] for g in groups})}")


if __name__ == "__main__":
    main()
