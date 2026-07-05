"""
원천 filing 드릴다운 — 표준화된 재무 값이 어느 공시(rcept_no)에서 왔는지.

fin2 는 (기업·연도·기간·연결별도) 재무를 BS/IS/CF **각 statement 별 단일 source filing**
으로 조립한다(statement_source). 이 모듈은 그 source_rcept_no 를 기간별로 모아 DART 웹
뷰어 URL 과 함께 돌려준다 → "이 숫자 어디서 왔나"를 원문으로 연결(D2b).
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
        SELECT fiscal_year, statement, source_rcept_no
        FROM statement_source
        WHERE corp_code = :c AND basis = :b AND fiscal_period = :p
          AND is_stub = false
        ORDER BY fiscal_year DESC
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
