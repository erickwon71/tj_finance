"""
Valuation 페이지 — DCF(내재가치) + 배당 분석.

`analyzer.dcf_engine.run_dcf` · `analyzer.dividend_engine.analyze_dividend` 재사용
(= `run.py dcf` / `run.py dividend` 와 동일 수치). 대상 기업은 사이드바 focus_corp.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import cache, state
from app.format import fmt_amount, fmt_corp_identity, fmt_pct


def _won(v) -> str:
    return f"{v:,.0f}원" if v is not None else "—"


def _dcf_section(corp_code: str, stmt: str) -> None:
    st.subheader("📉 DCF 내재가치")
    with st.expander("가정(미입력 시 자동 추정)", expanded=False):
        c1, c2, c3 = st.columns(3)
        g_in = c1.number_input("FCF 성장률 % (0=자동)", value=0.0, step=1.0, key="dcf_g")
        w_in = c2.number_input("WACC % (0=자동)", value=0.0, step=0.5, key="dcf_w")
        tg = c3.number_input("영구성장률 %", value=2.5, step=0.5, key="dcf_tg") / 100.0
        years = int(st.slider("예측 기간(년)", 3, 10, 5, key="dcf_years"))

    user_growth = g_in / 100.0 if g_in else None
    user_wacc = w_in / 100.0 if w_in else None

    res = cache.dcf_cached(corp_code, user_growth, user_wacc, tg, years, stmt)
    if not res:
        st.info("DCF 계산 불가(재무/FCF 데이터 부족).")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("주당 적정가", _won(res.intrinsic_per_share))
    c2.metric("현재가", _won(res.current_price),
              help=f"기준일: {res.price_date}" if res.price_date else "기준일: 데이터 없음")
    sm = res.safety_margin
    c3.metric("안전마진", fmt_pct(sm) if sm is not None else "—",
              delta=("저평가" if sm and sm > 0 else "고평가") if sm is not None else None)
    c4.metric("자기자본가치", fmt_amount(res.equity_value))

    st.caption(
        f"성장률 {fmt_pct(res.fcf_growth)} ({res.growth_source}) · WACC {fmt_pct(res.wacc)} · "
        f"영구성장 {fmt_pct(res.terminal_growth)} · β {res.beta:.2f} · "
        f"기준FCF {fmt_amount(res.base_fcf)}")
    st.caption(f"💡 현재가 기준일: **{res.price_date}** (최신 거래일 종가) — 기업 시각화의 💰 밸류에이션 탭은 "
               f"FY말 종가 기준이라 값이 다를 수 있습니다."
               if res.price_date else "💡 현재가 기준일: — (주가 데이터 없음)")

    proj = pd.DataFrame(
        [(y, f"{fcf/1e8:,.0f}억", f"{pv/1e8:,.0f}억") for y, fcf, pv in res.projected_fcfs],
        columns=["연도", "예상 FCF", "현재가치(PV)"])
    st.dataframe(proj, hide_index=True, width="stretch")
    st.caption(f"영구가치 PV {fmt_amount(res.terminal_value_pv)} · "
               f"기업가치 {fmt_amount(res.enterprise_value)} · 순부채 {fmt_amount(res.net_debt)}")


def _dividend_section(corp_code: str, stmt: str) -> None:
    st.subheader("💵 배당 분석")
    summ = cache.dividend_cached(corp_code, 10, stmt)
    if not summ or not summ.years:
        st.info("배당 데이터가 없습니다.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("연속 배당", f"{summ.consecutive_years}년")
    c2.metric("3년 평균 수익률", fmt_pct(summ.avg_yield_3y) if summ.avg_yield_3y else "—")
    c3.metric("3년 평균 배당성향", fmt_pct(summ.avg_payout_3y) if summ.avg_payout_3y else "—")
    c4.metric("DPS CAGR(5Y)", fmt_pct(summ.dps_cagr_5y) if summ.dps_cagr_5y else "—")

    rows = []
    for y in summ.years:
        rows.append({
            "FY": y.fiscal_year,
            "DPS": _won(y.dps),
            "배당수익률": fmt_pct(y.div_yield) if y.div_yield else "—",
            "배당성향": fmt_pct(y.payout_ratio) if y.payout_ratio else "—",
            "총배당": fmt_amount(y.dividends_paid),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"{'연결' if stmt=='consolidated' else '별도'} 기준 · `run.py dividend` 와 동일")


def render() -> None:
    st.header("💎 밸류에이션")
    corp_code = state.get_focus_corp()
    if not corp_code:
        st.info("좌측 사이드바에서 기업을 선택하세요.")
        return
    meta = cache.resolve_corp(corp_code)
    if not meta:
        st.warning(f"기업을 찾을 수 없습니다: {corp_code}")
        return
    st.subheader(fmt_corp_identity(meta["corp_name"], meta["corp_code"],
                                   meta.get("stock_code"), meta.get("market")))
    stmt = state.get_stmt_type()
    _dcf_section(corp_code, stmt)
    st.divider()
    _dividend_section(corp_code, stmt)
