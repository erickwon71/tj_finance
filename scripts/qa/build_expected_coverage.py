"""Build the per-company expected data-coverage baseline for the QA sweep (docs/qa §4).

Produces docs/qa/results/expected_coverage.csv with one row per active target
company: corp_code, corp_name, stock_code, market, fiscal_month, earliest_fy,
latest_fy. This is the ground-truth range the Tier-1 sweep uses to decide
whether a missing period is an allowed edge (before earliest_fy / after
latest_fy) or a mid-series gap.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from collector.db import get_session

QUERY = """
SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month,
       MIN(s.fiscal_year) AS earliest_fy, MAX(s.fiscal_year) AS latest_fy,
       COUNT(DISTINCT s.fiscal_year) AS distinct_fy_count
FROM corporations c
JOIN std_financials_v2 s ON s.corp_code = c.corp_code
WHERE c.is_active = TRUE
  AND COALESCE(c.coverage_class, 'periodic') <> 'non_periodic'
GROUP BY c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
ORDER BY c.market, c.corp_name;
"""

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "qa", "results", "expected_coverage.csv",
)


def main():
    with get_session() as session:
        rows = session.execute(text(QUERY)).fetchall()

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "corp_code", "corp_name", "stock_code", "market", "fiscal_month",
            "earliest_fy", "latest_fy", "distinct_fy_count",
        ])
        for r in rows:
            writer.writerow(list(r))

    span_gap = sum(
        1 for r in rows
        if r.latest_fy is not None and r.earliest_fy is not None
        and (r.latest_fy - r.earliest_fy + 1) != r.distinct_fy_count
    )
    print(f"companies: {len(rows)}")
    print(f"companies with fewer distinct FY than span (candidate mid-gaps at FY grain): {span_gap}")
    print(f"wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
