"""corp의 인접 연도 규모(자산/자본) 조회 — 자기모순 후보의 정합성(스파이크) 확인용."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

if __name__ == "__main__":
    corp = sys.argv[1]
    with get_session() as session:
        rows = session.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type,
                   total_assets, total_equity, retained_earnings, revenue
            FROM std_financials_v3 WHERE corp_code=:c
            ORDER BY fiscal_year, fiscal_period, statement_type
        """), {"c": corp}).fetchall()
        for r in rows:
            print(r)
