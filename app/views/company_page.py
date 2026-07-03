"""
Company (시각화) 페이지 — Phase 1 + 분기 + 주가·재무 결합.

연간(FY) / 분기(달력분기 CQ1~CQ4 이산) 재무표(억원) + 밸류에이션(최신 FY) +
주가 차트(log) + 주가·재무 결합 차트 + CSV export(raw 원).
수치는 analyzer 엔진(load_standard_financials / compute_multiples)·calendar_financials 재사용.
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from app import cache, state
from app.components.export import download_button
from app.format import corp_notes, fmt_amount, fmt_corp_identity, fmt_notes, fmt_pct, fmt_ratio
from app.views import metric_panel
from app.views.chart_panel import (
    render_price_chart, render_price_financial_combined, render_valuation_band,
    render_pershare_panel)

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


def _band_verdict(percentile: float, metric: str) -> str:
    """자기 역사 대비 저/고평가 판정. 멀티플은 낮을수록 싸고, 배당수익률은 높을수록 싸다."""
    cheapness = percentile if metric == "dividend_yield" else (100 - percentile)
    if cheapness >= 75:
        return "🟢 역사적 저평가권 (싸다)"
    if cheapness <= 25:
        return "🔴 역사적 고평가권 (비싸다)"
    return "🟡 역사적 중립권"


def _valuation_bands(corp_code: str) -> None:
    """일별 멀티플의 과거 분포 + 현재 위치(밴드). '자기 역사 대비 싸다/비싸다'."""
    from app.data.valuation_bands import BAND_METRICS, band_stats

    st.divider()
    st.markdown("#### 📉 밸류에이션 밴드 — 자기 역사 대비 (2015~)")
    keys = list(BAND_METRICS)
    labels = [BAND_METRICS[k][0] for k in keys]
    sel = st.selectbox("지표", labels, key="vband_metric", label_visibility="collapsed")
    metric = keys[labels.index(sel)]
    label, is_pct = BAND_METRICS[metric]

    series = cache.valuation_series(corp_code, metric, 2015)
    if not series or len(series) < 30:
        st.info("밴드를 그릴 만큼의 일별 멀티플 데이터가 없습니다.")
        return
    stats = band_stats([r["value"] for r in series])
    mult = 100.0 if is_pct else 1.0
    unit = "%" if is_pct else "x"
    c1, c2, c3 = st.columns(3)
    c1.metric(f"현재 {label}", f"{stats['current']*mult:,.1f}{unit}")
    c2.metric("역사적 백분위", f"{stats['percentile']:.0f}%",
              help="현재값이 과거 분포에서 차지하는 위치(0=최저, 100=최고)")
    c3.metric("판정", _band_verdict(stats["percentile"], metric))
    st.caption(f"중앙값 {stats['median']*mult:,.1f}{unit} · 범위 "
               f"{stats['min']*mult:,.1f}~{stats['max']*mult:,.1f}{unit} · {stats['n']:,}거래일")
    render_valuation_band(series, stats, label, is_pct, key=f"vband_{metric}")


def _per_share_trends(corp_code: str, stmt: str) -> None:
    """주당지표(EPS/BPS/FCF-per-share) + 발행주식수 추이(자사주/희석). 연간(FY) 기준."""
    rows_raw, _ = cache.annual_series(corp_code, stmt, 15)
    recs = []
    for r in rows_raw:
        sh = r.get("shares_out")
        if not sh:
            continue
        ni = r.get("controlling_ni") if r.get("controlling_ni") is not None else r.get("net_income")
        eq = r.get("controlling_equity") if r.get("controlling_equity") is not None else r.get("total_equity")
        fcf = r.get("fcf")
        recs.append({
            "year": r["fiscal_year"], "shares_out": sh,
            "eps": (ni / sh) if ni is not None else None,
            "bps": (eq / sh) if eq is not None else None,
            "fcf_ps": (fcf / sh) if fcf is not None else None,
        })
    if len(recs) < 2:
        return
    recs.sort(key=lambda x: x["year"])
    st.divider()
    st.markdown("#### 📐 주당지표 · 발행주식수 추이 (FY, 현재 주식수 기준)")
    first, last = recs[0], recs[-1]
    chg = (last["shares_out"] / first["shares_out"] - 1) * 100 if first["shares_out"] else 0.0
    trend = ("자사주 매입 등 감소" if chg < -1 else "증자·희석 등 증가" if chg > 1 else "거의 불변")
    st.caption(f"발행주식수 {first['year']}→{last['year']}: **{chg:+.1f}%** ({trend})")
    render_pershare_panel(recs, key="pershare")


def _executives_panel(corp_code: str) -> None:
    """임원 현황(지배구조) 로스터 — 최신 사업보고서 기준."""
    yr, rows = cache.executives_roster(corp_code)
    if not rows:
        st.info("임원 데이터가 없습니다. (수집: `python scripts/collect_executives.py --corps "
                f"{corp_code} --year 2024`)")
        return
    st.markdown(f"#### 👔 임원 현황 — {yr} 사업보고서 · {len(rows)}명")
    reg = sum(1 for r in rows if r["is_registered"])
    fem = sum(1 for r in rows if r.get("gender") == "여")
    c1, c2, c3 = st.columns(3)
    c1.metric("임원 수", f"{len(rows)}명")
    c2.metric("등기임원", f"{reg}명")
    c3.metric("여성", f"{fem}명 ({fem/len(rows)*100:.0f}%)" if rows else "—")
    df = pd.DataFrame([{
        "성명": r["name"], "직위": r.get("position") or "—",
        "등기": "등기" if r["is_registered"] else "미등기" if r["is_registered"] is False else "—",
        "상근": "상근" if r["is_fulltime"] else "비상근" if r["is_fulltime"] is False else "—",
        "담당업무": r.get("responsibility") or "—",
        "최대주주관계": r.get("shareholder_rel") or "—",
        "재직기간": r.get("tenure_period") or "—",
        "주요경력": r.get("main_career") or "—",
    } for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("출처: DART 임원현황(exctvSttus). 보수(개별 5억+)는 별도 공시라 미포함.")


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


def _report_viewer(corp_code: str) -> None:
    """선택 기업의 연도별 정기보고서 원문 — DART 웹뷰어 링크 + 로컬 원문 다운로드."""
    reports = cache.corp_reports(corp_code)
    if not reports:
        return
    with st.expander("📄 공시 원문 보기 (사업·반기·분기 보고서)", expanded=False):
        # 인덱스 기반 선택 → 같은 해 1분기/3분기 등 동일 라벨 충돌에도 안전
        idx = st.selectbox("보고서 선택", range(len(reports)),
                           format_func=lambda i: reports[i]["label"],
                           key=f"report_pick_{corp_code}")
        r = reports[idx]
        c1, c2 = st.columns([1, 1])
        c1.link_button("DART에서 원문 보기 ↗", r["dart_url"], width="stretch")
        fp = r.get("file_path")
        if fp and os.path.exists(fp):
            c2.download_button(
                "원문 파일 내려받기", data=cache.report_file_bytes(fp),
                file_name=os.path.basename(fp), mime="application/xml",
                width="stretch", key=f"report_dl_{corp_code}")
        else:
            c2.caption("로컬 원문 파일 없음 (DART 링크 이용)")
        st.caption(f"{r['report_nm']} · 접수번호 {r['rcept_no']}")


def _master_tab(corp_code: str, stmt: str, meta: dict) -> None:
    """대가(Master) 지표 — Buffett/Piotroski(엔진) + Graham/Greenblatt/Lynch/Fisher."""
    from analyzer.buffett_engine import compute_buffett
    from app.compute.master_metrics import compute_master

    rows, used = cache.annual_series(corp_code, stmt, years=10)
    if not rows:
        st.info("연간 재무 데이터가 없어 대가지표를 계산할 수 없습니다.")
        return
    mv = cache.company_multiples(corp_code, stmt)
    market_cap = mv.get("market_cap") if mv else None
    shares = mv.get("shares_out") if mv else None
    price = (market_cap / shares) if (market_cap and shares) else None

    bm = compute_buffett(rows, market_cap)
    mm = compute_master(rows, market_cap, price)
    st.caption(f"최신 FY 기준 · {'연결' if used=='consolidated' else '별도'}"
               + ("" if market_cap else " · ⚠ 시총 없음(가격기반 지표 제한)"))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Buffett / Piotroski**")
        st.dataframe(pd.DataFrame([
            ("Piotroski F", bm.score_badge()),
            ("Owner's Earnings", bm.oe_in_eok()),
            ("FCF품질(CFO/NI)", fmt_ratio(bm.fcf_quality)),
            ("ROIC", fmt_pct(bm.roic)),
            ("ROIC 5Y평균", fmt_pct(bm.roic_5y_avg)),
            ("배당성향", fmt_pct(bm.payout_ratio)),
        ], columns=["지표", "값"]).set_index("지표"), width="stretch")
    with c2:
        st.markdown("**Graham**")
        st.dataframe(pd.DataFrame([
            ("EPS", f"{mm.eps:,.0f}원" if mm.eps else "—"),
            ("BPS", f"{mm.bps:,.0f}원" if mm.bps else "—"),
            ("Graham Number", f"{mm.graham_number:,.0f}원" if mm.graham_number else "—"),
            ("Graham 상승여력", fmt_pct(mm.graham_upside)),
            ("NCAV/주가", fmt_ratio(mm.ncav_to_price)),
            ("PER×PBR(≤22.5)", fmt_ratio(mm.per_pbr, decimals=1)),
            ("EPS 흑자연수", f"{mm.eps_positive_years}년" if mm.eps_positive_years is not None else "—"),
        ], columns=["지표", "값"]).set_index("지표"), width="stretch")
    with c3:
        st.markdown("**Greenblatt / Lynch / Fisher**")
        st.dataframe(pd.DataFrame([
            ("이익수익률(EY)", fmt_pct(mm.earnings_yield)),
            ("투하자본수익률(ROC)", fmt_pct(mm.return_on_capital)),
            ("PEG(Lynch)", fmt_ratio(mm.peg, decimals=2)),
            ("R&D/매출(Fisher)", fmt_pct(mm.rd_to_revenue)),
            ("매출총이익률 변화", fmt_pct(mm.gross_margin_delta)),
        ], columns=["지표", "값"]).set_index("지표"), width="stretch")

    st.caption("※ Graham Number=√(22.5·EPS·BPS) · EY=EBIT/EV · ROC=EBIT/(순운전자본+순고정자산) · "
               "PEG=PER/순이익성장%. 마법공식 종합랭크는 스크리너에서 모집단 횡단면으로 산출.")


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

    notes = corp_notes(fiscal_month=meta.get("fiscal_month"),
                       used_stmt=used_stmt, requested_stmt=requested_stmt)
    st.subheader(fmt_corp_identity(
        meta["corp_name"], meta["corp_code"], meta.get("stock_code"),
        meta.get("market")) + fmt_notes(notes))
    if notes:
        st.caption("기업명 옆 **(주n)** 표시의 뜻은 좌측 메뉴 **ℹ️ 도움말** 페이지를 참고하세요.")

    _report_viewer(corp_code)

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
    TABS = ["📑 재무제표", "📊 지표", "💰 밸류에이션", "🏆 대가지표",
            "📈 주가", "📊 주가·재무 결합", "👔 임원"]
    active = st.radio("화면", TABS, horizontal=True, key="company_tab",
                      label_visibility="collapsed")

    # ── 재무제표 ──
    if active == TABS[0]:
        if grain == "quarter":
            st.caption("분기 = 달력분기 이산값 · IS/CF = 3개월 발생액, BS = 분기말 잔액 스냅샷")
        # 전체 기간 로드 후 슬라이더로 표시 구간 선택(표가 기간=컬럼이라 과거 분기/연도도 열람)
        if grain == "quarter":
            full, _ = cache.quarter_series(corp_code, requested_stmt, quarters=400)
        else:
            full, _ = cache.annual_series(corp_code, requested_stmt, years=200)
        full_labels = _period_labels(full, grain)          # 최신→과거
        chrono = list(reversed(full_labels))               # 과거→최신
        sel_labels = full_labels
        if len(chrono) >= 2:
            default_n = min(12 if grain == "quarter" else 10, len(chrono))
            start, end = st.select_slider(
                "표시 기간 (구간 선택)", options=chrono,
                value=(chrono[-default_n], chrono[-1]), key=f"fin_range_{grain}")
            i0, i1 = chrono.index(start), chrono.index(end)
            win = set(chrono[i0:i1 + 1])
            sel_labels = [lb for lb in full_labels if lb in win]
        fseries = [r for r, lb in zip(full, full_labels) if lb in set(sel_labels)]
        st.caption(f"표시 {len(sel_labels)}개 기간 (전체 {len(chrono)}개 중) · 표는 가로 스크롤")

        raw_sections = {}
        for label, items in _SECTIONS:
            raw_df = _section_raw_df(fseries, items, sel_labels)
            raw_sections[label] = raw_df
            _show_statement(label, raw_df)
        combined = pd.concat(raw_sections.values(), keys=raw_sections.keys(),
                             names=["구분", "항목"])
        suffix = "quarter" if grain == "quarter" else "annual"
        download_button(
            combined, filename=f"{meta['corp_name']}_{corp_code}_{suffix}_won.csv",
            label="⬇ 재무제표 CSV (원 단위, 선택 구간)", key="fin_csv")

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

        _valuation_bands(corp_code)
        _per_share_trends(corp_code, requested_stmt)

    # ── 대가지표 (Buffett·Piotroski·Graham·Greenblatt·Lynch·Fisher) ──
    elif active == TABS[3]:
        _master_tab(corp_code, requested_stmt, meta)

    # ── 주가 ──
    elif active == TABS[4]:
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
    elif active == TABS[5]:
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

    # ── 임원 (지배구조) ──
    elif active == TABS[6]:
        _executives_panel(corp_code)
