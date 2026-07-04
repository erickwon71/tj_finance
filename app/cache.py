"""
DB 로더의 st.cache_data 래퍼.

Streamlit 전체 재실행 모델에서 매 상호작용마다 DB 를 다시 치지 않도록, 모든 조회는
이 모듈을 경유해 캐시한다. 데이터 레이어(app/data/*)는 UI 비의존으로 유지하고, 캐싱
정책(키·ttl·용량)은 여기 한곳에서 관리한다.

## 캐싱 정책 (TTL)
데이터는 **하루 1회**(launchd 매일 18:00 수집)만 바뀌므로 세션 중에는 사실상 정적이다.
따라서 조회를 성격별로 나눠 TTL 을 둔다:
  - `TTL_HEAVY`(30분) — DB 스캔이 무겁거나 엔진 계산이 붙는 조회(재무·주가 시계열,
    스크리너 모집단/윈도우, 멀티플·DCF·배당·비교). 하루 1회 갱신이라 길게 잡아도 안전.
  - `TTL_LIGHT`(10분) — 가벼운 식별 조회(기업 검색·해석·보고서 목록). 입력이 다양해
    자주 무효화되므로 굳이 길게 잡지 않는다.
  - `TTL_SMOKE`(1분) — 헬스/카운트 스모크(table_counts).

## 캐싱 정책 (용량, max_entries)
corp_code·종목·파라미터 조합으로 키가 갈리는 조회는 활성 보통주 ~2.5천 곱하기 조합만큼
엔트리가 늘 수 있어 메모리 상한(`max_entries`)을 둔다(LRU 축출). 팬아웃이 없는(연도 정도)
조회는 상한을 생략한다.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Optional

import streamlit as st

from app.data import corp as _corp
from app.data import series as _series

# ── TTL 등급(초) ─────────────────────────────────────────
TTL_HEAVY = 1800   # 30분 — 무거운 DB/엔진 조회(일 1회 갱신이라 길게)
TTL_LIGHT = 600    # 10분 — 가벼운 식별 조회
TTL_SMOKE = 60     # 1분  — 헬스/카운트


# ── 기업 ─────────────────────────────────────────────────
@st.cache_data(ttl=TTL_LIGHT, show_spinner=False, max_entries=256)
def search_corps(query: str, limit: int = 30) -> list[dict]:
    return _corp.search_corps(query, limit)


@st.cache_data(ttl=TTL_LIGHT, show_spinner=False, max_entries=512)
def resolve_corp(corp_code: str) -> Optional[dict]:
    return _corp.resolve_corp(corp_code)


@st.cache_data(ttl=TTL_SMOKE, show_spinner=False)
def table_counts() -> dict:
    return _corp.table_counts()


@st.cache_data(ttl=TTL_LIGHT, show_spinner=False, max_entries=256)
def corp_reports(corp_code: str) -> list[dict]:
    """기업 정기보고서(사업/반기/분기) 목록 + DART 원문 URL + 로컬 파일경로."""
    from app.data import reports as _reports
    return _reports.list_reports(corp_code)


@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=8)
def report_file_bytes(path: str) -> bytes:
    """로컬 공시 원문 파일 바이트(다운로드용). 경로별 1회 읽기 캐시(대용량 재읽기 방지)."""
    with open(path, "rb") as fh:
        return fh.read()


# ── 재무 / 주가 시계열 ───────────────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def annual_series(corp_code: str, statement_type: str, years: int = 10) -> tuple[list[dict], str]:
    """연간 재무 시계열 + 실제 사용 basis (연결→별도 폴백)."""
    return _series.load_annual_series_with_fallback(corp_code, statement_type, years)


@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def quarter_series(corp_code: str, statement_type: str, quarters: int = 16) -> tuple[list[dict], str]:
    """분기 이산 재무 시계열 + 실제 사용 basis (연결→별도 폴백)."""
    return _series.load_quarter_series_with_fallback(corp_code, statement_type, quarters)


@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=256)
def price_series(stock_code: str, start: Optional[date], end: Optional[date]) -> list[dict]:
    return _series.load_price_series(stock_code, start, end)


@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def price_bounds(stock_code: str) -> tuple[Optional[date], Optional[date]]:
    return _series.price_date_bounds(stock_code)


# ── 스크리너 모집단 (최신 FY 전수) ───────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner="스크리닝 데이터 로드 중…")
def screen_population(fiscal_year: Optional[int] = None) -> list[dict]:
    """필터 없는 전체 모집단(가장 무거운 조회). 필터·정렬은 페이지에서 메모리로 적용."""
    from app.data.screen_window import load_population

    return load_population(fiscal_year)


@st.cache_data(ttl=TTL_HEAVY, show_spinner="윈도우 집계 중…", max_entries=32)
def screen_base_frame(n_periods: int, method: str, statement_type: str,
                      grain: str = "annual", fiscal_year: Optional[int] = None):
    """
    윈도우 로드(연간 FY / 분기 달력분기) + 집계(average/CAGR/YoY) → 기업당 1행 base DataFrame.
    퀀트 패스(필터·정렬·한도)는 이 frame 에 메모리로 적용. (n,method,stmt,grain,fy)별 1회 캐시.
    조합 키가 많아 max_entries 로 상한(LRU).
    """
    from app.compute.screen_eval import build_base_frame
    from app.data.screen_window import load_screening_window

    window = load_screening_window(n_periods, fiscal_year, statement_type, grain)
    return build_base_frame(window, method, n_periods, grain)


# ── 분기 변화(매출·영업이익 YoY/QoQ) ─────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False)
def quarter_change_years(statement_type: str) -> list[int]:
    from app.data.quarter_change import available_calendar_years
    return available_calendar_years(statement_type)


@st.cache_data(ttl=TTL_HEAVY, show_spinner="분기 변화 로드 중…", max_entries=32)
def quarter_change(cal_year: int, quarter: str, statement_type: str):
    """(연도,분기)별 전 대상기업 매출·영업이익 YoY/QoQ 증감. (rows, total_targets)."""
    from app.data.quarter_change import load_quarter_change
    return load_quarter_change(cal_year, quarter, statement_type)


# ── 비교 / DCF / 배당 (대가·밸류에이션 페이지) ───────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner="기업 비교 중…", max_entries=64)
def compare_companies(corp_codes: tuple, statement_type: str) -> list[dict]:
    """analyzer.comparator.compare 재사용(run.py compare 동일). 캐시 키=정렬불요 튜플."""
    from analyzer.comparator import compare

    return compare(list(corp_codes), statement_type)


@st.cache_data(ttl=TTL_HEAVY, show_spinner="DCF 계산 중…", max_entries=128)
def dcf_cached(corp_code: str, user_growth, user_wacc, terminal_growth: float,
               dcf_years: int, statement_type: str):
    """analyzer.dcf_engine.run_dcf 재사용(베타/주가 조회 포함이라 캐시)."""
    from analyzer.dcf_engine import run_dcf

    return run_dcf(corp_code, user_growth=user_growth, user_wacc=user_wacc,
                   terminal_growth=terminal_growth, dcf_years=dcf_years,
                   statement_type=statement_type)


@st.cache_data(ttl=TTL_HEAVY, show_spinner="배당 분석 중…", max_entries=256)
def dividend_cached(corp_code: str, years: int, statement_type: str):
    """analyzer.dividend_engine.analyze_dividend 재사용."""
    from analyzer.dividend_engine import analyze_dividend

    return analyze_dividend(corp_code, years=years, statement_type=statement_type)


# ── 섹터 피어 벤치마킹 ────────────────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=1024)
def peer_benchmark(corp_code: str, fiscal_year: Optional[int] = None) -> Optional[dict]:
    """대상 기업의 업종 피어 벤치마크. 캐시된 스크리너 모집단 재사용."""
    from app.data import peers as _peers
    pop = screen_population(fiscal_year)
    return _peers.load_peer_benchmark(corp_code, pop)


# ── 데이터 신뢰 (Gate B) ─────────────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=1024)
def trust_summary(corp_code: str) -> dict:
    """Gate B 감사 요약(신뢰 배지). app.data.trust 위임."""
    from app.data import trust as _trust
    return _trust.load_trust(corp_code)


# ── 시장조치/규제 지정 이력 ─────────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=1024)
def regulatory_status(corp_code: str) -> dict:
    """관리종목/상장폐지/매매정지 등 활성 flag + 이력. app.data.regulatory 위임."""
    from app.data import regulatory as _regulatory
    return _regulatory.load_regulatory_status(corp_code)


# ── 자본이벤트 (증자·감자·CB/BW/EB·자기주식) ─────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=1024)
def capital_events(corp_code: str) -> list[dict]:
    """자본이벤트 이력. app.data.capital 위임."""
    from app.data import capital as _capital
    return _capital.load_capital_events(corp_code)


# ── 지배구조 (임원 현황) ─────────────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def executives_roster(corp_code: str):
    """최신 사업연도 임원 로스터. app.data.governance 위임."""
    from app.data import governance as _gov
    return _gov.load_executives(corp_code)


@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def ownership_status(corp_code: str):
    """최신 사업연도 대주주/지분 현황(B3). app.data.governance 위임."""
    from app.data import governance as _gov
    return _gov.load_ownership(corp_code)


# ── 밸류에이션 밴드 (일별 멀티플 시계열) ─────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
def valuation_series(corp_code: str, metric: str, since_year: Optional[int] = None) -> list[dict]:
    """valuation_daily 일별 멀티플 시계열(밴드용). app.data.valuation_bands 위임."""
    from app.data import valuation_bands as _vb
    return _vb.load_valuation_series(corp_code, metric, since_year)


# ── 밸류에이션 멀티플 (최신 FY) ──────────────────────────
@st.cache_data(ttl=TTL_HEAVY, show_spinner=False, max_entries=512)
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
