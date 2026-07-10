"""PRD 03 §5.2 — corporations.account_bucket 태깅(general / financial).

금융(financial) = 매출원가/매출총이익 구조가 없고(<20% FY행), 다음 금융수익 구조 중 하나를 가진 corp:
  · 보험: 보험료/수입보험료/책임준비금 라벨
  · 증권: 순영업수익/순수수료손익 라벨
  · 카드·캐피탈: 신용판매수익/할부금융수익/리스수익(매출원가 부재 상태에서)
  · 은행: 이자수익(is.finance_income) 최대액 > 영업이익 최대액(이자수익이 주영업수익)
이 조건으로 플랫폼·지주(NAVER·카카오·SKT 등 무-COGS 이나 이자수익 incidental)는 general 로 분리.
나머지 = general. 멱등(재실행 가능). 시각화 peer 그룹·버킷별 지표 적용용.

usage: python scripts/tag_account_bucket.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text
from collector.db import get_session

# 라벨 마커(fact_v2.acode, IS duration). 정규화된 라벨(공백제거) 기준 LIKE.
_INSURANCE = ("%보험료%", "%수입보험료%", "%책임준비금%")
_SECURITIES = ("%순영업수익%", "%순수수료손익%", "%순수수료수익%")
_CARD = ("%신용판매수익%", "%할부금융수익%", "%리스금융수익%")


def classify(session) -> dict[str, str]:
    # 1) FY 연결/별도 통틀어 cogs/gross_profit 존재율(매출원가 구조 유무).
    cogs = {r.corp_code: (r.fy_rows, r.cogs_rows) for r in session.execute(text("""
        SELECT corp_code,
               count(*) FILTER (WHERE fiscal_period='FY') fy_rows,
               count(*) FILTER (WHERE fiscal_period='FY' AND (cogs IS NOT NULL OR gross_profit IS NOT NULL)) cogs_rows
        FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false)
          AND NOT COALESCE(is_discrete,false) AND fiscal_year>=2010
        GROUP BY corp_code"""))}

    # 2) 금융수익 마커 보유 corp 집합(fact_v2 IS duration).
    def label_corps(patterns) -> set[str]:
        out: set[str] = set()
        for p in patterns:
            out |= {r[0] for r in session.execute(text("""
                SELECT DISTINCT corp_code FROM fact_v2
                WHERE source_format='xml_text' AND period_kind='duration' AND acode LIKE :p"""), {"p": p})}
        return out
    insurance = label_corps(_INSURANCE)
    securities = label_corps(_SECURITIES)
    card = label_corps(_CARD)

    # 3) 은행: 이자수익(is.finance_income) 최대액 ≥ 영업이익 최대액×3(이자수익이 주영업수익).
    bank_sql = text("""
        WITH fin AS (
            SELECT corp_code, max(abs(amount_won)) fi FROM fact_v2
            WHERE canonical_account='is.finance_income' AND basis IN ('consolidated','separate')
              AND col_index=0 AND NOT is_dimensional GROUP BY corp_code),
        op AS (
            SELECT corp_code, max(abs(operating_income)) oi FROM std_financials_v2
            WHERE version=1 AND operating_income IS NOT NULL GROUP BY corp_code)
        SELECT fin.corp_code FROM fin JOIN op USING (corp_code)
        WHERE fin.fi > GREATEST(op.oi, 1) * 3""")
    bank = {r[0] for r in session.execute(bank_sql)}

    buckets: dict[str, str] = {}
    fin_markers = insurance | securities | card | bank
    for corp, (fy_rows, cogs_rows) in cogs.items():
        no_cogs = fy_rows >= 1 and (cogs_rows / fy_rows) < 0.2
        buckets[corp] = "financial" if (no_cogs and corp in fin_markers) else "general"
    return buckets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with get_session() as s:
        buckets = classify(s)
        from collections import Counter
        dist = Counter(buckets.values())
        logger.info(f"[bucket] 분류: {dict(dist)}")
        fin = sorted(c for c, b in buckets.items() if b == "financial")
        names = {r[0]: r[1] for r in s.execute(text(
            "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:c)"), {"c": fin})}
        logger.info(f"[bucket] financial {len(fin)}사 예: " + ", ".join(names.get(c, c) for c in fin[:20]))
        if args.dry_run:
            return
        for corp, b in buckets.items():
            s.execute(text("UPDATE corporations SET account_bucket=:b WHERE corp_code=:c"),
                      {"b": b, "c": corp})
        s.commit()
        logger.success(f"[bucket] account_bucket 태깅 완료 — {len(buckets)}사 ({dict(dist)})")


if __name__ == "__main__":
    main()
