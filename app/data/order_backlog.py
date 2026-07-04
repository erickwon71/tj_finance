"""수주상황(수주잔고) 로더 — B1(→B4). UI 비의존.

order_backlog(collector/order_backlog.py::sync_order_backlog 가 채움, 사업보고서 본문
"수주상황"/"수주계약 현황" 표에서 파싱)를 소비.

주의(v1 범위, 2026-07-05): 계약잔액/수주잔고 컬럼이 명시된 표만 채택 — 진행률%만 있고
계약잔액이 없는 표(대우건설/한화오션류 "진행률적용 수주계약 현황")는 파생 신뢰도가
낮아 수집 자체에서 스킵되므로, 해당 유형 기업은 데이터가 없을 수 있다(추출 실패 아님).
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session


def load_order_backlog(corp_code: str) -> dict:
    """corp 의 최신 사업보고서 기준 수주상황 행. 반환: {available, fiscal_year, rows}."""
    with get_session() as s:
        latest_fy = s.execute(text(
            "SELECT max(fiscal_year) FROM order_backlog WHERE corp_code = :c"), {"c": corp_code}).scalar()
        if latest_fy is None:
            return {"available": False}
        rows = s.execute(text("""
            SELECT category, backlog_amt, new_orders, completed, unit
            FROM order_backlog WHERE corp_code = :c AND fiscal_year = :fy
            ORDER BY id
        """), {"c": corp_code, "fy": latest_fy}).fetchall()
    return {
        "available": True,
        "fiscal_year": latest_fy,
        "rows": [dict(r._mapping) for r in rows],
    }
