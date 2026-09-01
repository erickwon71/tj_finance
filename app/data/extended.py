"""
확장 재무항목 로더 — extended_financials 뷰(fact_v2×statement_source) 소비.

METRIC_REGISTRY 에 없는 캐노니컬 계정(app/registry/extended.py::EXTENDED_CATALOG)을 연간(FY)
단위로 로드한다. v1 은 연간만 지원 — H1/Q3 는 뷰가 누적 as-filed 값이라 분기 이산화가
안 돼 있어(마스터 PRD 결정 1) 분기 그레인은 빈 결과를 반환한다.

period_end 는 std_financials_v3 에서 조인해 가져온다(동일 (corp,fy,fp,basis) 의 기존 연간
시계열과 동일 축 정렬을 보장 — chart_panel.render_metric_chart 가 period_end 로 정렬).

★2026-09-01(fact_v2/std_v2 GC 트랙 §6-2) — std_financials_v2 → v3 로 전환. v3 는
PK 가 (corp_code,fiscal_year,fiscal_period,statement_type) 뿐이라 v2 의
version=1/NOT is_stub/NOT is_discrete 조건 자체가 불필요(애초에 한 키에 행이 0~1개).
조인 커버리지 실측(2026-09-01): extended_financials FY 키 54,623건 중 v2 매칭 54,600건
(99.96%) → v3 매칭 54,619건(99.99%) — 회귀 없음, 오히려 소폭 개선.
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session


def load_extended_all(corp_code: str, basis: str = "consolidated") -> list[dict]:
    """
    corp 의 연간(FY) 확장 재무항목 전체(카탈로그 필터 없음 — app/registry/extended.py 가
    caller 측에서 필요한 것만 골라 쓴다). fiscal_year 내림차순.
    """
    with get_session() as session:
        rows = session.execute(text("""
            SELECT e.fiscal_year, e.canonical_account, e.amount_won, s.period_end
            FROM extended_financials e
            JOIN std_financials_v3 s
              ON s.corp_code = e.corp_code AND s.fiscal_year = e.fiscal_year
             AND s.fiscal_period = e.fiscal_period AND s.statement_type = e.basis
            WHERE e.corp_code = :corp AND e.basis = :basis AND e.fiscal_period = 'FY'
            ORDER BY e.fiscal_year DESC
        """), {"corp": corp_code, "basis": basis}).fetchall()
        return [
            {"fiscal_year": r[0], "canonical_account": r[1],
             "amount_won": r[2], "period_end": r[3]}
            for r in rows
        ]
