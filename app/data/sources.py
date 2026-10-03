"""
원천 filing 드릴다운 — 표준화된 재무 값이 어느 공시(rcept_no)에서 왔는지.

표준화(계층3)는 (기업·연도·기간·연결별도) 재무를 BS/IS/CF **각 statement 별 source filing**
으로 조립한다(std_financials_v3.source_rcepts JSONB). 이 모듈은 그 rcept 를 기간별로 모아 DART
웹뷰어 URL 과 함께 돌려준다 → "이 숫자 어디서 왔나"를 원문으로 연결(D2b).
★2026-10-03 — 옛 statement_source 테이블(2026-09-01 이후 갱신 중단, 폐기)에서 v3 로 이식했다.
v3 는 정정본 반영 결과가 곧 화면 값이라 출처 표시가 더 정확하다(두 출처가 갈린 9,224건은 전부
v3 가 더 나중의 [기재정정]을 반영한 경우).
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session
from app.data.reports import DART_VIEWER

_STMT_ORDER = ("BS", "IS", "CF")


def load_statement_sources(
    corp_code: str, basis: str, fiscal_period: str = "FY",
) -> dict[int, list[dict]]:
    """
    연도 → [{rcept_no, statements:[BS,IS,CF...], dart_url}] (같은 filing 은 합쳐 1개).

    부분 기재정정이면 BS/IS/CF 가 서로 다른 filing 을 source 로 가질 수 있어, 연도별로
    distinct rcept 를 묶어 각 filing 이 어느 statement 를 공급했는지 보인다.
    """
    sql = text("""
        SELECT s.fiscal_year, k.key AS statement, k.value #>> '{}' AS source_rcept_no
        FROM std_financials_v3 s, jsonb_each(s.source_rcepts) k
        WHERE s.corp_code = :c AND s.statement_type = :b AND s.fiscal_period = :p
          AND jsonb_typeof(k.value) = 'string'
        ORDER BY s.fiscal_year DESC
    """)
    params = {"c": corp_code, "b": basis, "p": fiscal_period}
    with get_session() as s:
        rows = s.execute(sql, params).mappings().fetchall()

    by_year: dict[int, dict[str, list[str]]] = {}
    for r in rows:
        fy = r["fiscal_year"]
        by_year.setdefault(fy, {}).setdefault(r["source_rcept_no"], []).append(r["statement"])

    out: dict[int, list[dict]] = {}
    for fy, per_rcept in by_year.items():
        items = []
        for rcept, stmts in per_rcept.items():
            ordered = [s for s in _STMT_ORDER if s in stmts]
            items.append({
                "rcept_no": rcept,
                "statements": ordered,
                "dart_url": DART_VIEWER.format(rcept=rcept),
            })
        out[fy] = items
    return out
