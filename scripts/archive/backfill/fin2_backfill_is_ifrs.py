"""
is_ifrs 백필 — std_v2 own-report 행에 회계기준(IFRS vs K-GAAP) 플래그 채우기.

배경: 전수 재추출 후 own-report standardize 가 is_ifrs 를 NULL 로 두어(build.py 기존 동작)
K-GAAP↔IFRS 구분이 소실됨(Layer 2 calendarization 시계열 단절 식별용). build.py 에 도출 로직
(_derive_is_ifrs)을 추가했고, 본 스크립트는 **기존 행을 재표준화 없이 1회 UPDATE** 로 채운다.

규칙(=_derive_is_ifrs 와 동일):
  is_ifrs = (source 보고서 중 Track A(xbrl_acode) fact 존재)  -- IFRS 택소노미
            OR (fiscal_year >= 2011)                          -- K-IFRS 의무적용 FY2011~
대상: own-report 행만(kgaap_gap=False 고정, comparative_fallback=파생행은 None 유지).
멱등(재실행 안전).

실행(빠름, 인덱스 ix_fact_v2_rcept_no 활용):
    PYTHONPATH=. .venv_tj_finance/bin/python scripts/fin2_backfill_is_ifrs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

UPDATE_SQL = """
UPDATE std_financials_v2 s SET is_ifrs = (
    s.fiscal_year >= 2011 OR EXISTS (
        SELECT 1 FROM fact_v2 f
        WHERE f.source_format = 'xbrl_acode'
          AND f.rcept_no IN (s.bs_rcept, s.is_rcept, s.cf_rcept)
    )
)
WHERE s.version = 1
  AND NOT (s.applied_rules @> '["kgaap_gap"]')
  AND NOT (s.applied_rules @> '["comparative_fallback"]')
"""


def main() -> None:
    with get_session() as session:
        before = session.execute(text("""
            SELECT
              SUM(CASE WHEN is_ifrs IS TRUE THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_ifrs IS FALSE THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_ifrs IS NULL THEN 1 ELSE 0 END)
            FROM std_financials_v2 WHERE version = 1
        """)).fetchone()
        logger.info(f"[is_ifrs] before — true={before[0] or 0:,} false={before[1] or 0:,} null={before[2] or 0:,}")

        result = session.execute(text(UPDATE_SQL))
        session.commit()
        logger.success(f"[is_ifrs] own-report 행 {result.rowcount:,} UPDATE 완료")

        after = session.execute(text("""
            SELECT
              SUM(CASE WHEN is_ifrs IS TRUE THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_ifrs IS FALSE THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_ifrs IS NULL THEN 1 ELSE 0 END)
            FROM std_financials_v2 WHERE version = 1
        """)).fetchone()
        logger.info(f"[is_ifrs] after  — true={after[0] or 0:,} false={after[1] or 0:,} null={after[2] or 0:,}")
        # K-GAAP(false) 연도 분포 점검
        logger.info("[is_ifrs] is_ifrs=false 연도 분포(상위):")
        for r in session.execute(text("""
            SELECT fiscal_year, COUNT(*) FROM std_financials_v2
            WHERE version=1 AND is_ifrs IS FALSE GROUP BY fiscal_year ORDER BY fiscal_year DESC LIMIT 8""")):
            logger.info(f"    {r[0]}: {r[1]:,}")


if __name__ == "__main__":
    main()
