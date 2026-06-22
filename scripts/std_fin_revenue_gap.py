"""금융 버킷 corp 중 std revenue/operating_income NULL 인 (corp,fy) 의 실제 IS top-line 라벨 진단.
→ account_maps 보강 후보(어떤 라벨이 매출/영업수익인데 매핑 안 됐나)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from scripts.std_coverage_gap import classify_financial


def main():
    with get_session() as s:
        financial = classify_financial(s)
        # 금융 corp 중 FY 연결 revenue NULL 행
        rows = s.execute(text("""
            SELECT corp_code, fiscal_year, is_rcept FROM std_financials_v2
            WHERE version=1 AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false)
              AND fiscal_period='FY' AND statement_type='consolidated' AND fiscal_year>=2015
              AND revenue IS NULL AND corp_code = ANY(:c)
            ORDER BY fiscal_year DESC
        """), {"c": list(financial)}).fetchall()
        print(f"=== 금융 corp FY 연결 revenue NULL: {len(rows)}행 ===")
        # 이 corp 들의 IS fact 중 top-line 후보 라벨(미매핑) 빈도
        corps_null = list({r.corp_code for r in rows})
        labels = Counter()
        for (acode, n) in s.execute(text("""
            SELECT acode, count(*) FROM fact_v2
            WHERE corp_code = ANY(:c) AND canonical_account IS NULL AND source_format='xml_text'
              AND period_kind='duration'
              AND (acode LIKE '%수익%' OR acode LIKE '%매출%' OR acode LIKE '%영업%')
              AND acode !~ '^[0-9]' AND char_length(acode) BETWEEN 3 AND 22
            GROUP BY acode ORDER BY 2 DESC LIMIT 30
        """), {"c": corps_null}):
            labels[acode] = n
        print("\n=== revenue-NULL 금융 corp 미매핑 '수익/매출/영업' 라벨 상위 ===")
        for lbl, n in labels.most_common(30):
            print(f"  {n:>6}  {lbl}")
        # 대표 corp 몇 개 이름
        names = {r[0]: r[1] for r in s.execute(text(
            "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:c)"),
            {"c": corps_null})}
        print("\n=== revenue-NULL corp 예 ===")
        for cc in corps_null[:20]:
            print(f"  {cc} {names.get(cc,'?')}")


if __name__ == "__main__":
    main()
