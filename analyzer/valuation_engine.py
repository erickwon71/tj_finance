"""
밸류에이션 멀티플 계산 엔진

PER, PBR, PSR, PCR, EV/EBITDA, EV/EBIT 계산.
주가/시총은 price_fetcher를 통해 조회.

사용 예:
    from analyzer.valuation_engine import compute_multiples
    mults = compute_multiples(sf, corp_code="00126380", period_end=date(2024, 12, 31))
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from loguru import logger


@dataclass
class ValuationMultiples:
    """밸류에이션 멀티플 컨테이너."""

    market_cap:   Optional[int]   = None  # 시가총액 (원)
    close_price:  Optional[int]   = None  # 주가 (원)
    shares_out:   Optional[int]   = None  # 상장주식수
    price_date:   Optional[date]  = None  # 위 주가/시총의 실제 거래일(기준일 — UI 캡션용)

    per:          Optional[float] = None  # Price/Earnings
    pbr:          Optional[float] = None  # Price/Book Value
    psr:          Optional[float] = None  # Price/Sales
    pcr:          Optional[float] = None  # Price/Cash Flow (CFO 기준)
    ev:           Optional[int]   = None  # Enterprise Value
    ev_ebitda:    Optional[float] = None  # EV/EBITDA
    ev_ebit:      Optional[float] = None  # EV/EBIT (EV/영업이익)
    ev_fcf:       Optional[float] = None  # EV/FCF

    def fmt(self, attr: str, suffix: str = "x", decimal: int = 1) -> str:
        v = getattr(self, attr, None)
        if v is None:
            return "—"
        return f"{v:.{decimal}f}{suffix}"

    def fmt_cap(self, attr: str = "market_cap") -> str:
        """시총/EV를 조 단위로 포맷."""
        v = getattr(self, attr, None)
        if v is None:
            return "—"
        t = v / 1e12
        return f"{t:.1f}조원"


def compute_multiples(
    sf,                          # StandardFinancial 또는 dict
    corp_code: str,
    stock_code: Optional[str] = None,
    period_end: Optional[date] = None,
) -> ValuationMultiples:
    """
    밸류에이션 멀티플 계산.

    Args:
        sf:          StandardFinancial 행 또는 dict
        corp_code:   DART 기업코드
        stock_code:  KRX 종목코드. None이면 DB에서 조회
        period_end:  기준일. None이면 sf.period_end 사용
    """
    from analyzer.price_fetcher import get_market_data

    def _get(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    # 종목코드 조회
    if stock_code is None:
        stock_code = _lookup_stock_code(corp_code)
    if stock_code is None:
        logger.debug(f"종목코드 없음: {corp_code}")
        return ValuationMultiples()

    # 기준일
    if period_end is None:
        period_end = _get(sf, "period_end")
    if period_end is None:
        period_end = date.today()

    # 기준 사업연도
    fiscal_year_val = _get(sf, "fiscal_year")

    # 주가 / 시총 조회 (corp_code 전달 → DART로 상장주식수 보완)
    price_data = get_market_data(
        stock_code,
        as_of_date=period_end,
        corp_code=corp_code,
        fiscal_year=fiscal_year_val,
    )
    if not price_data:
        return ValuationMultiples()

    mv = ValuationMultiples(
        market_cap  = price_data.get("market_cap"),
        close_price = price_data.get("close_price"),
        shares_out  = price_data.get("shares_out"),
        price_date  = price_data.get("trade_date"),
    )

    mc = mv.market_cap
    if mc is None or mc <= 0:
        return mv

    # 재무 데이터
    ni       = _get(sf, "controlling_ni") or _get(sf, "net_income")
    eq       = _get(sf, "controlling_equity") or _get(sf, "total_equity")
    rev      = _get(sf, "revenue")
    cfo      = _get(sf, "cfo")
    ebitda   = _get(sf, "ebitda")
    op       = _get(sf, "operating_income")
    fcf      = _get(sf, "fcf")
    net_debt = _get(sf, "net_debt") or 0

    # EV = 시총 + 순부채
    mv.ev = mc + net_debt

    # PER: 순이익 > 0일 때만 의미 있음
    if ni and ni > 0:
        mv.per = mc / ni

    # PBR
    if eq and eq > 0:
        mv.pbr = mc / eq

    # PSR
    if rev and rev > 0:
        mv.psr = mc / rev

    # PCR
    if cfo and cfo > 0:
        mv.pcr = mc / cfo

    # EV/EBITDA
    if mv.ev and ebitda and ebitda > 0:
        mv.ev_ebitda = mv.ev / ebitda

    # EV/EBIT
    if mv.ev and op and op > 0:
        mv.ev_ebit = mv.ev / op

    # EV/FCF
    if mv.ev and fcf and fcf > 0:
        mv.ev_fcf = mv.ev / fcf

    return mv


def _lookup_stock_code(corp_code: str) -> Optional[str]:
    """DB에서 종목코드 조회."""
    try:
        from sqlalchemy import text
        from collector.db import get_session
        with get_session() as session:
            row = session.execute(
                text("SELECT stock_code FROM corporations WHERE corp_code = :c"),
                {"c": corp_code},
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None
