"""statement_magnitude_impossible 전수 위반 상세(어느 concept이 임계 초과인지) —
(가+라) 그룹 원문대조 세션용 워크리스트 작성.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

Q = """
SELECT corp_code, fiscal_year, fiscal_period, statement_type,
       total_assets, total_equity, retained_earnings, revenue
FROM std_financials_v3
WHERE COALESCE(data_quality,1) < 3
  AND (abs(total_assets) > 1e15 OR abs(total_equity) > 5e14
       OR abs(retained_earnings) > 5e14 OR abs(revenue) > 4e14)
ORDER BY corp_code, fiscal_year, fiscal_period, statement_type
"""

if __name__ == "__main__":
    with get_session() as session:
        rows = session.execute(text(Q)).fetchall()
        for r in rows:
            corp, fy, fp, basis, ta, te, re_, rev = r
            flags = []
            if ta and abs(ta) > 1e15: flags.append(f"assets={ta}")
            if te and abs(te) > 5e14: flags.append(f"equity={te}")
            if re_ and abs(re_) > 5e14: flags.append(f"RE={re_}")
            if rev and abs(rev) > 4e14: flags.append(f"revenue={rev}")
            print(corp, fy, fp, basis, "|", "; ".join(flags))
