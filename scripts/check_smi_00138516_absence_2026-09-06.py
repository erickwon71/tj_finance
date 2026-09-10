"""statement_magnitude_impossible 전수 조회 — 00138516이 빠졌는지, 그 외에 신규
위반이 없는지 확인 (unit_override 스코프 재빌드 후 회귀 확인).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

Q = """
SELECT corp_code, fiscal_year, fiscal_period, statement_type
FROM std_financials_v3
WHERE COALESCE(data_quality,1) < 3
  AND (abs(total_assets) > 1e15 OR abs(total_equity) > 5e14
       OR abs(retained_earnings) > 5e14 OR abs(revenue) > 4e14)
ORDER BY corp_code, fiscal_year, fiscal_period, statement_type
"""

if __name__ == "__main__":
    with get_session() as session:
        rows = session.execute(text(Q)).fetchall()
        print(f"total: {len(rows)}")
        for r in rows:
            print(r)
        print("---")
        print("00138516 present:", any(r[0] == "00138516" for r in rows))
