"""
시계열 로더 — 연간 재무 시계열 + 일별 주가 시계열.

UI 비의존. 재무 시계열은 검증된 analyzer.ratio_engine.load_standard_financials 를 재사용하고,
주가는 stock_prices 를 직접 조회한다(금액 raw 원).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text

from collector.db import get_session
from analyzer.ratio_engine import load_standard_financials


def load_annual_series(
    corp_code: str,
    statement_type: str = "consolidated",
    years: int = 10,
) -> list[dict]:
    """
    연간(FY) 표준 재무 시계열. 연도 내림차순(최신→과거).

    analyzer.ratio_engine.load_standard_financials(FY) 위임 — run.py analyze 와 동일 소스.
    """
    return load_standard_financials(corp_code, statement_type, "FY", years)


def load_annual_series_with_fallback(
    corp_code: str,
    statement_type: str = "consolidated",
    years: int = 10,
) -> tuple[list[dict], str]:
    """
    요청 basis 로 로드, 비면 반대 basis 로 폴백(print_analysis 패턴).
    반환: (sf_list, 실제_사용_basis).
    """
    rows = load_annual_series(corp_code, statement_type, years)
    if rows:
        return rows, statement_type
    other = "separate" if statement_type == "consolidated" else "consolidated"
    rows = load_annual_series(corp_code, other, years)
    return rows, (other if rows else statement_type)


_DISCRETE_QUARTERS = ("CQ1", "CQ2", "CQ3", "CQ4")


def load_quarter_series(
    corp_code: str,
    statement_type: str = "consolidated",
    quarters: int = 16,
) -> list[dict]:
    """
    분기 이산(discrete) 재무 시계열 — calendar_financials 의 달력분기 CQ1~CQ4.
    flow(IS/CF)=이산 3개월, stock(BS)=분기말 스냅샷. 최신→과거.
    """
    sql = """
        SELECT *
        FROM calendar_financials
        WHERE corp_code = :corp
          AND statement_type = :stype
          AND calendar_period IN ('CQ1', 'CQ2', 'CQ3', 'CQ4')
        ORDER BY calendar_year DESC, calendar_period DESC
        LIMIT :n
    """
    params = {"corp": corp_code, "stype": statement_type, "n": quarters}
    with get_session() as session:
        rows = session.execute(text(sql), params).mappings().fetchall()
    return [dict(r) for r in rows]


def load_quarter_series_with_fallback(
    corp_code: str,
    statement_type: str = "consolidated",
    quarters: int = 16,
) -> tuple[list[dict], str]:
    """분기 시계열 + 실제 사용 basis (연결→별도 폴백)."""
    rows = load_quarter_series(corp_code, statement_type, quarters)
    if rows:
        return rows, statement_type
    other = "separate" if statement_type == "consolidated" else "consolidated"
    rows = load_quarter_series(corp_code, other, quarters)
    return rows, (other if rows else statement_type)


def load_price_series(
    stock_code: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[dict]:
    """
    일별 주가 시계열(OHLCV + 시총). trade_date 오름차순.
    값은 raw 원. 단일 종목 조회라 ix_sp_stock_date 로 빠름.
    """
    if not stock_code:
        return []
    clauses = ["stock_code = :sc"]
    params: dict = {"sc": stock_code}
    if start is not None:
        clauses.append("trade_date >= :start")
        params["start"] = start
    if end is not None:
        clauses.append("trade_date <= :end")
        params["end"] = end
    sql = f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, market_cap
        FROM stock_prices
        WHERE {' AND '.join(clauses)}
        ORDER BY trade_date ASC
    """
    with get_session() as session:
        rows = session.execute(text(sql), params).mappings().fetchall()
    return [dict(r) for r in rows]


def price_date_bounds(stock_code: str) -> tuple[Optional[date], Optional[date]]:
    """해당 종목 주가의 최소/최대 거래일."""
    if not stock_code:
        return None, None
    sql = """
        SELECT min(trade_date) AS lo, max(trade_date) AS hi
        FROM stock_prices WHERE stock_code = :sc
    """
    with get_session() as session:
        row = session.execute(text(sql), {"sc": stock_code}).mappings().fetchone()
    if not row:
        return None, None
    return row["lo"], row["hi"]
