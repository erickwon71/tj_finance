"""PRD 03 §5.2 진단 — 일반/금융 2버킷별 std_v2 표준필드 커버리지(NULL률) + 미매핑 라벨 후보.

금융 버킷 분류(데이터 기반, 외부 업종표 불요): IS 에 매출원가·매출총이익이 거의 없고
영업수익/이자수익/수수료수익/보험료 구조를 가진 corp = 금융업(PRD 근거).

출력: ① 버킷별 corp 수 ② 버킷별 핵심 std 필드 NULL률 ③ 금융 corp 에서 자주 NULL 인
필드의 fact_v2 미매핑 라벨 상위(=account_maps 보강 후보).
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session

# 금융 분류용: 매출원가/매출총이익 부재 + 금융수익 구조 존재.
_FIN_REVENUE_LABELS = ("영업수익", "이자수익", "수수료수익", "보험료", "수입보험료", "순영업수익")
# 커버리지 점검 핵심 std 필드
_KEY_FIELDS = ("revenue", "operating_income", "net_income", "total_assets",
               "total_equity", "cfo", "cogs", "gross_profit")


def classify_financial(session) -> set[str]:
    """연결/별도 통틀어 FY 행에서 cogs·gross_profit 거의 없고 금융수익 라벨 보유 corp."""
    # corp 별 FY std_v2 의 cogs/gross_profit 존재율
    rows = session.execute(text("""
        SELECT corp_code,
               count(*) FILTER (WHERE fiscal_period='FY') AS fy_rows,
               count(*) FILTER (WHERE fiscal_period='FY' AND (cogs IS NOT NULL OR gross_profit IS NOT NULL)) AS cogs_rows
        FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false)
          AND NOT COALESCE(is_discrete,false) AND fiscal_year>=2015
        GROUP BY corp_code
    """)).fetchall()
    # 금융수익 라벨 보유 corp(fact_v2 acode)
    fin_label_corps = {r[0] for r in session.execute(text("""
        SELECT DISTINCT corp_code FROM fact_v2
        WHERE canonical_account='is.revenue' AND (
              acode LIKE '%영업수익%' OR acode LIKE '%이자수익%' OR acode LIKE '%수수료수익%'
              OR acode LIKE '%보험료%')
    """))}
    financial = set()
    for r in rows:
        if r.fy_rows >= 2 and r.cogs_rows / r.fy_rows < 0.2 and r.corp_code in fin_label_corps:
            financial.add(r.corp_code)
    return financial


def main():
    with get_session() as s:
        financial = classify_financial(s)
        print(f"=== 금융 버킷 corp: {len(financial)}사 ===")
        names = s.execute(text("""SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:c)"""),
                          {"c": list(financial)}).fetchall()
        print("  예:", ", ".join(f"{n[1]}" for n in names[:15]))

        # 버킷별 핵심 필드 NULL률 (FY, 연결, fy>=2015)
        print("\n=== 버킷별 핵심 std 필드 NULL률 (FY 연결 fy>=2015) ===")
        rows = s.execute(text("""
            SELECT corp_code, %s FROM std_financials_v2
            WHERE version=1 AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false)
              AND fiscal_period='FY' AND statement_type='consolidated' AND fiscal_year>=2015
        """ % ", ".join(_KEY_FIELDS))).fetchall()
        agg = {"financial": defaultdict(lambda: [0, 0]), "general": defaultdict(lambda: [0, 0])}
        for r in rows:
            bucket = "financial" if r.corp_code in financial else "general"
            for f in _KEY_FIELDS:
                agg[bucket][f][0] += 1
                if getattr(r, f) is None:
                    agg[bucket][f][1] += 1
        print(f"  {'field':18} {'일반 NULL%':>12} {'금융 NULL%':>12}")
        for f in _KEY_FIELDS:
            g = agg["general"][f]; fi = agg["financial"][f]
            gp = 100*g[1]/g[0] if g[0] else 0
            fp = 100*fi[1]/fi[0] if fi[0] else 0
            print(f"  {f:18} {gp:11.1f}% {fp:11.1f}%")

        # 금융 corp 에서 revenue/operating_income/net_income NULL 인 행의 fact_v2 미매핑 IS 라벨 후보
        print("\n=== 금융 corp 미매핑 IS 라벨 상위 (canonical NULL, account_maps 후보) ===")
        if financial:
            labels = Counter()
            for (acode, n) in s.execute(text("""
                SELECT acode, count(*) FROM fact_v2
                WHERE corp_code = ANY(:c) AND canonical_account IS NULL
                  AND source_format='xml_text' AND period_kind='duration'
                  AND acode !~ '^[0-9]' AND char_length(acode) BETWEEN 3 AND 20
                GROUP BY acode ORDER BY 2 DESC LIMIT 40
            """), {"c": list(financial)}):
                labels[acode] = n
            for lbl, n in labels.most_common(40):
                print(f"  {n:>7}  {lbl}")


if __name__ == "__main__":
    main()
