"""
Company (시각화) 페이지 — Phase 1 + 분기 + 주가·재무 결합.

연간(FY) / 분기(달력분기 CQ1~CQ4 이산) 재무표(억원) + 밸류에이션(최신 FY) +
주가 차트(log) + 주가·재무 결합 차트 + CSV export(raw 원).
수치는 analyzer 엔진(load_standard_financials / compute_multiples)·calendar_financials 재사용.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import cache, state
from app.components.export import download_button
from app.format import fmt_amount, fmt_corp_identity, fmt_ratio
from app.views import metric_panel
from app.views.chart_panel import render_price_chart, render_price_financial_combined

EOK = 100_000_000

_IS_ITEMS = [
    ("매출액", "revenue"), ("매출원가", "cogs"), ("매출총이익", "gross_profit"),
    ("판관비", "sga"), ("영업이익", "operating_income"), ("EBITDA", "ebitda"),
    ("순이익", "net_income"), ("지배주주순이익", "controlling_ni"),
]
_BS_ITEMS = [
    ("자산총계", "total_assets"), ("유동자산", "current_assets"), ("현금", "cash"),
    ("매출채권", "receivables"), ("재고자산", "inventory"), ("유형자산", "ppe"),
    ("무형자산", "intangibles"), ("부채총계", "total_liabilities"),
    ("유동부채", "current_liabilities"), ("단기차입금", "short_term_debt"),
    ("장기차입금", "long_term_debt"), ("자본총계", "total_equity"),
    ("이익잉여금", "retained_earnings"), ("순부채", "net_debt"),
]
_CF_ITEMS = [
    ("영업현금흐름(CFO)", "cfo"), ("투자현금흐름(CFI)", "cfi"), ("재무현금흐름(CFF)", "cff"),
    ("CAPEX", "capex"), ("잉여현금흐름(FCF)", "fcf"), ("배당금지급", "dividends_paid"),
    ("감가상각비(D&A)", "da_total"),
]
_SECTIONS = [("손익계산서", _IS_ITEMS), ("재무상태표", _BS_ITEMS), ("현금흐름표", _CF_ITEMS)]

# 결합 차트 오버레이용 핵심 항목
_FIN_METRICS = [
    ("매출액", "revenue"), ("영업이익", "operating_income"), ("순이익", "net_income"),
    ("지배주주순이익", "controlling_ni"), ("EBITDA", "ebitda"), ("자본총계", "total_equity"),
    ("잉여현금흐름(FCF)", "fcf"), ("CAPEX", "capex"),
]


def _period_labels(series: list[dict], grain: str) -> list[str]:
    if grain == "quarter":
        return [f"{r['calendar_year']} {r['calendar_period']}" for r in series]
    return [str(r["fiscal_year"]) for r in series]


def _section_raw_df(series: list[dict], items: list[tuple[str, str]],
                    labels: list[str]) -> pd.DataFrame:
    """라인×기간 raw 원 DataFrame. 기간 내림차순(최신 좌측)."""
    data = {label: [r.get(key) for r in series] for label, key in items}
    df = pd.DataFrame(data, index=labels).T
    df.columns = labels
    return df


def _show_statement(label: str, raw_df: pd.DataFrame) -> None:
    st.markdown(f"**{label}** (억원)")
    # 결측이 섞이면 object dtype 이 될 수 있어 표시용은 숫자로 강제 환산.
    # (CSV 는 raw_df 원본 정수를 그대로 사용하므로 정밀도 유지)
    disp = raw_df.apply(pd.to_numeric, errors="coerce") / EOK
    st.dataframe(
        disp.style.format(thousands=",", precision=0, na_rep="—"),
        width="stretch",
    )


def _valuation_df(mv: dict) -> pd.DataFrame:
    rows = [
        ("시가총액", fmt_amount(mv.get("market_cap"))),
        ("EV", fmt_amount(mv.get("ev"))),
        ("PER", fmt_ratio(mv.get("per"))),
        ("PBR", fmt_ratio(mv.get("pbr"))),
        ("PSR", fmt_ratio(mv.get("psr"))),
        ("PCR", fmt_ratio(mv.get("pcr"))),
        ("EV/EBITDA", fmt_ratio(mv.get("ev_ebitda"))),
        ("EV/EBIT", fmt_ratio(mv.get("ev_ebit"))),
        ("EV/FCF", fmt_ratio(mv.get("ev_fcf"))),
        ("EPS", f"{mv['eps']:,.0f}원" if mv.get("eps") else "—"),
        ("BPS", f"{mv['bps']:,.0f}원" if mv.get("bps") else "—"),
    ]
    return pd.DataFrame(rows, columns=["지표", "값"]).set_index("지표")


def _dq_banner(series: list[dict], grain: str) -> None:
    warn = []
    for sf, lbl in zip(series, _period_labels(series, grain)):
        dq = sf.get("data_quality", 1) or 0
        if dq >= 3:
            warn.append(f"🔴 {lbl}: 데이터 오류(DQ=3)")
        elif dq >= 2:
            warn.append(f"🟡 {lbl}: 데이터 경고(DQ=2)")
    if warn:
        st.warning(" · ".join(warn))


def _fin_points(series: list[dict], key: str) -> list[tuple]:
    pts = [(r["period_end"], r.get(key)) for r in series
           if r.get("period_end") and r.get(key) is not None]
    pts.sort(key=lambda t: t[0])
    return pts


def render() -> None:
    st.header("기업 시각화")

    corp_code = state.get_focus_corp()
    if not corp_code:
        st.info("좌측 사이드바에서 기업을 검색·선택하세요.")
        return

    meta = cache.resolve_corp(corp_code)
    if not meta:
        st.warning(f"기업을 찾을 수 없습니다: {corp_code}")
        return

    requested_stmt = state.get_stmt_type()
    grain = state.get_grain()

    # 기간 grain 에 따른 재무 시계열
    if grain == "quarter":
        series, used_stmt = cache.quarter_series(corp_code, requested_stmt, quarters=12)
    else:
        series, used_stmt = cache.annual_series(corp_code, requested_stmt, years=10)

    st.subheader(fmt_corp_identity(
        meta["corp_name"], meta["corp_code"], meta.get("stock_code"), meta.get("market")))

    if not series:
        st.warning(f"{'분기' if grain=='quarter' else '연간'} 표준화 재무제표 데이터가 없습니다.")
        return
    if used_stmt != requested_stmt:
        st.caption(f"※ {'연결' if requested_stmt=='consolidated' else '별도'} 데이터 없음 "
                   f"→ {'연결' if used_stmt=='consolidated' else '별도'} 표시")

    _dq_banner(series, grain)

    # 이상치 가드 — DB 는 보고서와 일치(Gate B)하나 소스 자체가 비정상일 수 있어 표시단계에서 플래그
    from app.compute.checks import financial_anomalies
    anomalies = financial_anomalies(series, grain)
    if anomalies:
        with st.expander(f"⚠ 이상치 점검 ({len(anomalies)}건) — 보고서 원값 확인 권장", expanded=True):
            for m in anomalies:
                st.markdown(f"- {m}")
            st.caption("※ DB 값은 공시 보고서와 100% 일치(Gate B 검증). 이 경고는 소스 보고서 자체의 "
                       "비정상 가능성(정정 전 오기재·이상 수치)을 알리는 표시용 신호입니다.")

    labels = _period_labels(series, grain)
    stock_code = meta.get("stock_code")
    lo, hi = cache.price_bounds(stock_code) if stock_code else (None, None)

    # 탭 = session_state 유지 라디오(사이드바 변경 등 재실행에도 보던 화면 유지)
    TABS = ["📑 재무제표", "📊 지표", "💰 밸류에이션", "📈 주가", "📊 주가·재무 결합"]
    active = st.radio("화면", TABS, horizontal=True, key="company_tab",
                      label_visibility="collapsed")

    # ── 재무제표 ──
    if active == TABS[0]:
        if grain == "quarter":
            st.caption("분기 = 달력분기 이산값 · IS/CF = 3개월 발생액, BS = 분기말 잔액 스냅샷")
        raw_sections = {}
        for label, items in _SECTIONS:
            raw_df = _section_raw_df(series, items, labels)
            raw_sections[label] = raw_df
            _show_statement(label, raw_df)
        combined = pd.concat(raw_sections.values(), keys=raw_sections.keys(),
                             names=["구분", "항목"])
        suffix = "quarter" if grain == "quarter" else "annual"
        download_button(
            combined, filename=f"{meta['corp_name']}_{corp_code}_{suffix}_won.csv",
            label="⬇ 재무제표 CSV (원 단위)", key="fin_csv")

    # ── 지표 (레지스트리 멀티셀렉트 + 그래프/표) ──
    elif active == TABS[1]:
        # 지표 탭은 전체 기간 사용(표=전체 표시, 그래프=슬라이더로 기간 조절)
        if grain == "quarter":
            mseries, _ = cache.quarter_series(corp_code, requested_stmt, quarters=400)
        else:
            mseries, _ = cache.annual_series(corp_code, requested_stmt, years=200)
        metric_panel.render(mseries, grain, meta["corp_name"], corp_code)

    # ── 밸류에이션 (항상 최신 FY 기준) ──
    elif active == TABS[2]:
        st.caption("연간(FY) 기준 — 분기 멀티플(TTM)은 후속 단계")
        mv = cache.company_multiples(corp_code, requested_stmt)
        if not mv or not mv.get("market_cap"):
            st.info("주가/시총 데이터가 없어 밸류에이션을 계산할 수 없습니다.")
        else:
            st.markdown(f"**{mv.get('fiscal_year')} FY 기준** · "
                        f"{'연결' if mv.get('used_stmt')=='consolidated' else '별도'}")
            st.dataframe(_valuation_df(mv), width="stretch")

    # ── 주가 ──
    elif active == TABS[3]:
        if not stock_code:
            st.info("비상장 또는 종목코드 없음.")
        elif not hi:
            st.info("주가 데이터가 없습니다.")
        else:
            from datetime import timedelta
            c1, c2, c3 = st.columns([2, 1, 1])
            rng = c1.radio("기간", ["1Y", "3Y", "5Y", "10Y", "전체"],
                           index=2, horizontal=True, key="px_range")
            log_scale = c2.toggle("로그 스케일", value=True, key="px_log")
            candle = c3.toggle("캔들", value=False, key="px_candle")
            span = {"1Y": 365, "3Y": 365*3, "5Y": 365*5, "10Y": 365*10}.get(rng)
            start = max(hi - timedelta(days=span), lo) if span else lo
            rows = cache.price_series(stock_code, start, hi)
            render_price_chart(rows, title=f"{meta['corp_name']} ({stock_code})",
                               log_scale=log_scale, candlestick=candle, key="px_chart")

    # ── 주가·재무 결합 ──
    elif active == TABS[4]:
        if not stock_code or not hi:
            st.info("주가 데이터가 없어 결합 차트를 표시할 수 없습니다.")
        else:
            c1, c2 = st.columns([3, 1])
            # 기간(연간/분기)은 좌측 사이드바 선택을 그대로 따른다(단일 컨트롤).
            metric_labels = c1.multiselect(
                "재무 항목 (최대 3개)", [l for l, _ in _FIN_METRICS],
                default=["매출액"], max_selections=3, key="combo_metrics")
            log2 = c2.toggle("로그 스케일(주가)", value=True, key="combo_log")

            # 결합용 더 긴 시계열 (사이드바 grain 기준)
            if grain == "quarter":
                cseries, _ = cache.quarter_series(corp_code, requested_stmt, quarters=40)
            else:
                cseries, _ = cache.annual_series(corp_code, requested_stmt, years=15)

            fin_series = []
            for ml in metric_labels:
                pts = _fin_points(cseries, dict(_FIN_METRICS)[ml])
                if pts:
                    fin_series.append((ml, pts))

            if not fin_series:
                st.info("선택한 재무 항목의 "
                        f"{'분기' if grain=='quarter' else '연간'} 데이터가 없습니다.")
            else:
                start = min(pts[0][0] for _, pts in fin_series)
                prows = cache.price_series(stock_code, start, hi)
                render_price_financial_combined(
                    prows, fin_series, grain=grain, log_scale=log2, key="combo_chart")
                grain_note = "분기 이산(3개월)" if grain == "quarter" else "연간 FY"
                style = "막대" if len(fin_series) == 1 else "라인"
                st.caption(f"좌축=주가(원{', log' if log2 else ''}) · 우축=재무(억원, {style}) · "
                           f"{grain_note} · 재무항목 {len(fin_series)}개 · 기간 전환은 좌측 사이드바")
