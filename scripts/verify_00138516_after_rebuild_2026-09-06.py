"""Post-rebuild verification for 00138516 (아남전자) FY2006 unit-override case.

docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

CORP = "00138516"


def main():
    with get_session() as session:
        rows = session.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type, retained_earnings,
                   total_assets, total_equity, unit_overrides
            FROM std_financials_v3
            WHERE corp_code=:c
            ORDER BY fiscal_year, fiscal_period, statement_type
        """), {"c": CORP}).fetchall()
        for r in rows:
            print(r)


if __name__ == "__main__":
    main()
