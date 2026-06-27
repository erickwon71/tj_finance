"""
DB 로더의 st.cache_data 래퍼.

Streamlit 전체 재실행 모델에서 매 상호작용마다 DB 를 다시 치지 않도록, 모든 조회는
이 모듈을 경유해 캐시한다. 데이터 레이어(app/data/*)는 UI 비의존으로 유지하고, 캐싱
정책(키·ttl)은 여기 한곳에서 관리한다.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Optional

import streamlit as st

from app.data import corp as _corp
from app.data import series as _series


# ── 기업 ─────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def search_corps(query: str, limit: int = 30) -> list[dict]:
    return _corp.search_corps(query, limit)


@st.cache_data(ttl=600, show_spinner=False)
def resolve_corp(corp_code: str) -> Optional[dict]:
    return _corp.resolve_corp(corp_code)


@st.cache_data(ttl=60, show_spinner=False)
def table_counts() -> dict:
    return _corp.table_counts()


# ── 재무 / 주가 시계열 ───────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def annual_series(corp_code: str, statement_type: str, years: int = 10) -> tuple[list[dict], str]:
    """연간 재무 시계열 + 실제 사용 basis (연결→별도 폴백)."""
    return _series.load_annual_series_with_fallback(corp_code, statement_type, years)


@st.cache_data(ttl=600, show_spinner=False)
def quarter_series(corp_code: str, statement_type: str, quarters: int = 16) -> tuple[list[dict], str]:
    """분기 이산 재무 시계열 + 실제 사용 basis (연결→별도 폴백)."""
    return _series.load_quarter_series_with_fallback(corp_code, statement_type, quarters)


@st.cache_data(ttl=600, show_spinner=False)
def price_series(stock_code: str, start: Optional[date], end: Optional[date]) -> list[dict]:
    return _series.load_price_series(stock_code, start, end)


@st.cache_data(ttl=600, show_spinner=False)
def price_bounds(stock_code: str) -> tuple[Optional[date], Optional[date]]:
    return _series.price_date_bounds(stock_code)


# ── 스크리너 모집단 (최신 FY 전수) ───────────────────────
@st.cache_data(ttl=600, show_spinner="스크리닝 데이터 로드 중…")
def screen_population(fiscal_year: Optional[int] = None) -> list[dict]:
    """필터 없는 전체 모집단(가장 무거운 조회). 필터·정렬은 페이지에서 메모리로 적용."""
    from app.data.screen_window import load_population

    return load_population(fiscal_year)


@st.cache_data(ttl=600, show_spinner="윈도우 집계 중…")
def screen_base_frame(n_years: int, method: str, statement_type: str,
                      fiscal_year: Optional[int] = None):
    """
    윈도우 로드 + 집계(average/CAGR/YoY) → 기업당 1행 base DataFrame.
    퀀트 패스(필터·정렬·한도)는 이 frame 에 메모리로 적용. (n,method,stmt,fy)별 1회 캐시.
    """
    from app.compute.screen_eval import build_base_frame
    from app.data.screen_window import load_screening_window

    window = load_screening_window(n_years, fiscal_year, statement_type)
    return build_base_frame(window, method, n_years)


# ── 비교 / DCF / 배당 (대가·밸류에이션 페이지) ───────────
@st.cache_data(ttl=600, show_spinner="기업 비교 중…")
def compare_companies(corp_codes: tuple, statement_type: str) -> list[dict]:
    """analyzer.comparator.compare 재사용(run.py compare 동일). 캐시 키=정렬불요 튜플."""
    from analyzer.comparator import compare

    return compare(list(corp_codes), statement_type)


@st.cache_data(ttl=600, show_spinner="DCF 계산 중…")
def dcf_cached(corp_code: str, user_growth, user_wacc, terminal_growth: float,
               dcf_years: int, statement_type: str):
    """analyzer.dcf_engine.run_dcf 재사용(베타/주가 조회 포함이라 캐시)."""
    from analyzer.dcf_engine import run_dcf

    return run_dcf(corp_code, user_growth=user_growth, user_wacc=user_wacc,
                   terminal_growth=terminal_growth, dcf_years=dcf_years,
                   statement_type=statement_type)


@st.cache_data(ttl=600, show_spinner="배당 분석 중…")
def dividend_cached(corp_code: str, years: int, statement_type: str):
    """analyzer.dividend_engine.analyze_dividend 재사용."""
    from analyzer.dividend_engine import analyze_dividend

    return analyze_dividend(corp_code, years=years, statement_type=statement_type)


# ── 밸류에이션 멀티플 (최신 FY) ──────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def company_multiples(corp_code: str, statement_type: str) -> Optional[dict]:
    """
    최신 FY 기준 밸류에이션 멀티플. analyzer.valuation_engine.compute_multiples 재사용
    (run.py analyze 와 동일). EPS/BPS 는 재무·주식수로 파생.
    """
    from analyzer.valuation_engine import compute_multiples

    rows, used = _series.load_annual_series_with_fallback(corp_code, statement_type, 2)
    if not rows:
        return None
    curr = rows[0]
    meta = _corp.resolve_corp(corp_code)
    stock_code = meta.get("stock_code") if meta else None
    period_end = curr.get("period_end")

    mv = compute_multiples(curr, corp_code, stock_code, period_end)
    d = asdict(mv)

    ni = curr.get("controlling_ni") or curr.get("net_income")
    eq = curr.get("controlling_equity") or curr.get("total_equity")
    shares = mv.shares_out
    d["eps"] = (ni / shares) if (ni and shares) else None
    d["bps"] = (eq / shares) if (eq and shares) else None
    d["fiscal_year"] = curr.get("fiscal_year")
    d["used_stmt"] = used
    return d
