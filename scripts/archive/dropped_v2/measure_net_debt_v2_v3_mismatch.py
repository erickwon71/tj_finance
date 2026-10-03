"""net_debt v2/v3 mismatch measurement — same methodology as docs/plans/
valuation_daily_blockers_da_netdebt_design_2026-08-30.md §2-2/§2-5.

Compares std_financials_v3.net_debt against std_financials_v2.net_debt (the v2 filter
mirrors the matview's own `finnd` LATERAL in collector/db.py: version=1, not is_discrete,
not is_stub) for FY rows both sides have, per fiscal year. Read-only, fast (indexed PK
join) — safe to run any time, before/after a std_v3 rebuild.

Usage:
    python scripts/measure_net_debt_v2_v3_mismatch.py [--label STEP_LABEL]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text

DB_URL = "postgresql://localhost/tj_finance"

SQL = """
SELECT v3.fiscal_year,
       count(*) AS both_have,
       count(*) FILTER (WHERE v3.net_debt IS DISTINCT FROM v2.net_debt) AS mismatch
FROM std_financials_v3 v3
JOIN std_financials_v2 v2
  ON v2.corp_code = v3.corp_code AND v2.fiscal_year = v3.fiscal_year
 AND v2.fiscal_period = 'FY' AND v2.statement_type = v3.statement_type
 AND v2.version = 1 AND NOT COALESCE(v2.is_discrete, false) AND NOT COALESCE(v2.is_stub, false)
WHERE v3.fiscal_period = 'FY'
  AND v3.net_debt IS NOT NULL AND v2.net_debt IS NOT NULL
  AND v3.fiscal_year = ANY(:years)
GROUP BY v3.fiscal_year
ORDER BY v3.fiscal_year;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2024, 2025])
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    eng = create_engine(DB_URL)
    with eng.connect() as c:
        rows = c.execute(text(SQL), {"years": args.years}).fetchall()

    ts = datetime.now().isoformat(timespec="seconds")
    header = f"[{ts}]" + (f" label={args.label}" if args.label else "")
    print(header)
    print(f"{'fy':>6} {'both_have':>10} {'mismatch':>9} {'ratio':>8}")
    for fy, both_have, mismatch in rows:
        ratio = mismatch / both_have if both_have else 0.0
        print(f"{fy:>6} {both_have:>10} {mismatch:>9} {ratio:>7.1%}")


if __name__ == "__main__":
    main()
