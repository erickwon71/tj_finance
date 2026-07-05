"""
기재정정(amendment) 인식 — C9(W6 대응).

DB는 as-filed(reconcile 가 statement_source 로 statement별 최적 source 선택)라, 기재정정본이
있는 기간이라도 사용자는 그 사실을 알기 어렵다. 이 모듈은 (corp, 기간)별로 **기재정정 filing
존재 여부 + DB 가 실제 정정본을 source 로 썼는지**를 요약해 신뢰 배지에서 투명하게 알린다.

reconcile 는 적시 기재정정([기재정정], 최초제출 +400일 내)을 우선 채택하므로 대개 정정본이
반영되나, 지연/첨부정정([첨부정정])은 원본 유지 — 그런 '원본유지' 기간을 사용자에게 표시.
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session

_SQL = text("""
    WITH amend AS (
        SELECT DISTINCT fiscal_year, fiscal_period
        FROM filings
        WHERE corp_code = :c AND is_amendment = true AND fiscal_period IS NOT NULL
    ),
    src AS (   -- DB 가 이 기간에 실제 채택한 source rcept 이 정정본인지(consolidated·별도 통합)
        SELECT ss.fiscal_year, ss.fiscal_period, bool_or(fl.is_amendment) AS uses_amend
        FROM statement_source ss
        JOIN filings fl ON fl.rcept_no = ss.source_rcept_no
        WHERE ss.corp_code = :c
        GROUP BY ss.fiscal_year, ss.fiscal_period
    )
    SELECT a.fiscal_year, a.fiscal_period, COALESCE(s.uses_amend, false) AS uses_amend
    FROM amend a
    LEFT JOIN src s ON s.fiscal_year = a.fiscal_year AND s.fiscal_period = a.fiscal_period
    ORDER BY a.fiscal_year DESC,
             array_position(ARRAY['FY','H1','Q3','Q1'], a.fiscal_period)
""")


def load_amendment_summary(corp_code: str) -> dict:
    """기재정정 이력 요약.

    반환: {n_amended, n_reflects, n_original, periods:[{fiscal_year, fiscal_period, uses_amend}]}.
      n_amended  = 기재정정 filing 이 존재하는 기간 수
      n_reflects = 그 중 DB source 가 정정본인 기간 수(정정 반영)
      n_original = DB 가 원본 유지(지연·첨부정정 등) — 정정 내용 미반영 가능 → 확인 권장
    """
    with get_session() as s:
        rows = s.execute(_SQL, {"c": corp_code}).fetchall()
    periods = [{"fiscal_year": r[0], "fiscal_period": r[1], "uses_amend": bool(r[2])}
               for r in rows]
    n_reflects = sum(1 for p in periods if p["uses_amend"])
    return {
        "n_amended": len(periods),
        "n_reflects": n_reflects,
        "n_original": len(periods) - n_reflects,
        "periods": periods,
    }
