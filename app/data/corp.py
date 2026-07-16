"""
기업 조회 헬퍼 (corporations 테이블).

UI 비의존 — get_session() + text() 패턴(프로젝트 표준). 캐싱은 app/cache.py 가 감싼다.
대상은 시장 거래가능 활성 보통주(stock_code 보유 + is_active).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from collector.db import get_session


def search_corps(query: str, limit: int = 30) -> list[dict]:
    """
    기업명 부분일치 또는 종목코드 접두 일치로 활성 보통주를 검색.

    반환: [{corp_code, corp_name, stock_code, market, fiscal_month}, ...]
          corp_name 선두 일치를 우선 정렬.
    """
    q = (query or "").strip()
    if not q:
        return []

    sql = """
        SELECT corp_code, corp_name, stock_code, market, fiscal_month
        FROM corporations
        WHERE is_active = TRUE
          AND stock_code IS NOT NULL
          AND (corp_name ILIKE :like OR stock_code LIKE :prefix)
        ORDER BY
          CASE WHEN corp_name ILIKE :startswith THEN 0 ELSE 1 END,
          length(corp_name),
          corp_name
        LIMIT :limit
    """
    params = {
        "like": f"%{q}%",
        "prefix": f"{q}%",
        "startswith": f"{q}%",
        "limit": limit,
    }
    with get_session() as session:
        rows = session.execute(text(sql), params).mappings().fetchall()
    return [dict(r) for r in rows]


def resolve_corp(corp_code: str) -> Optional[dict]:
    """corp_code → 기업 메타. 없으면 None."""
    if not corp_code:
        return None
    sql = """
        SELECT corp_code, corp_name, stock_code, market, fiscal_month,
               is_active, coverage_class, induty_code
        FROM corporations
        WHERE corp_code = :cc
    """
    with get_session() as session:
        row = session.execute(text(sql), {"cc": corp_code}).mappings().fetchone()
    return dict(row) if row else None


def table_counts() -> dict:
    """DB 연결 스모크용 — 핵심 테이블 행수 요약."""
    sql = """
        SELECT
          (SELECT count(*) FROM corporations WHERE is_active AND stock_code IS NOT NULL) AS active_corps,
          (SELECT count(*) FROM standard_financials)  AS std_rows,
          (SELECT count(*) FROM stock_prices)         AS price_rows
    """
    with get_session() as session:
        row = session.execute(text(sql)).mappings().fetchone()
    return dict(row) if row else {}
