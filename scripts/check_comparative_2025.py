"""
COMPARATIVE_ONLY 의 2025 청크가 진짜 양성(비교연도)인지, 아니면 2025 자체보고서
라벨링 버그가 숨은 건지 표본 검증.

removed_keys 에서 2025 COMPARATIVE_ONLY 후보 corp 몇 개를 뽑아, 각 corp 의 fact_v2
report 기간 분포(2024~2026)와 std_v2 보유 기간을 출력한다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session

d = json.load(open("/tmp/parity_v2.json"))
# 2025 separate/consolidated removed corps
corps2025 = []
seen = set()
for k in d["removed_keys"]:
    p = k.split("|")
    if p[1] == "2025" and p[0] not in seen:
        seen.add(p[0]); corps2025.append(p[0])
    if len(corps2025) >= 6:
        break
print("표본 corp(2025 removed):", corps2025)

with get_session() as s:
    for corp in corps2025:
        print(f"\n=== corp {corp} ===")
        rows = s.execute(text("""
            SELECT report_fiscal_year, report_fiscal_period, basis,
                   count(*) n,
                   count(*) FILTER (WHERE context_fiscal_year=2025) n_ctx2025
            FROM fact_v2
            WHERE corp_code=:c AND report_fiscal_year BETWEEN 2024 AND 2026
            GROUP BY 1,2,3 ORDER BY 1,2,3
        """), {"c": corp}).fetchall()
        print(" fact_v2 report(2024-26): (rfy, rper, basis, n, n_ctx2025)")
        for r in rows:
            print("   ", tuple(r))
        sv = s.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type
            FROM std_financials_v2
            WHERE corp_code=:c AND fiscal_year BETWEEN 2024 AND 2026
            ORDER BY 1,2,3
        """), {"c": corp}).fetchall()
        print(" std_v2(2024-26):", [tuple(r) for r in sv])
