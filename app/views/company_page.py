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
from app.format import (corp_notes, fmt_amount, fmt_corp_identity, fmt_notes, fmt_pct,
                        fmt_ratio, render_dataframe)
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
    # st.dataframe 은 Styler 의 na_rep 을 반영하지 않아 결측이 "None" 으로 새어나온다.
    # 표시 직전에 셀을 직접 문자열화(천단위·정수)하고 결측은 "—" 로 치환한다.
    # (col.map 형태로 pandas 버전 무관하게 동작)
    text = disp.apply(lambda col: col.map(
        lambda v: "—" if pd.isna(v) else f"{v:,.0f}"))
    st.dataframe(text, width="stretch")


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

    # B2c — 자본이벤트 오버레이 + 잠재 희석 % (증자/감자/CB/BW/EB/자기주식)
    from app.data.capital import EVENT_LABELS, potential_dilution_pct, yearly_dilution_overlay
    events = cache.capital_events(corp_code)
    dilution_by_year = yearly_dilution_overlay(events)
    dil_pct = potential_dilution_pct(events, last["shares_out"])
    if dil_pct is not None:
        st.caption(f"⚗️ 잠재 희석(최근 3년 CB/BW/EB, 상한선 추정) — 현재 발행주식수 대비 "
                   f"**{dil_pct:+.1f}%** (전환/상환 상태 미반영, 실제보다 클 수 있음)")

    render_pershare_panel(recs, key="pershare", dilution_by_year=dilution_by_year)

    if events:
        with st.expander(f"자본이벤트 이력 ({len(events)}건)", expanded=False):
            df_ev = pd.DataFrame([{
                "접수일": e["filed_at"], "이사회결의일": e["board_date"],
                "구분": EVENT_LABELS.get(e["event_type"], e["event_type"]),
                "주식수 변동": f"{e['shares_delta']:+,}" if e["shares_delta"] is not None else "—",
                "접수번호": e["rcept_no"],
            } for e in events])
            st.dataframe(df_ev, hide_index=True, width="stretch")
            st.caption("출처: DART 주요사항보고서. CB/BW/EB는 전환·행사 전 잠재 주식수(상한선 추정). "
                       "자기주식 취득/처분은 총발행주식수 불변(유통주식만 영향).")


def _dilution_timeline(corp_code: str) -> None:
    """자본이벤트 타임라인(D3) — 증자/감자/CB·BW·EB/자기주식을 시간축에 배치 + 확정발행 누적."""
    from app.data.capital import dilution_timeline
    from app.views.chart_panel import render_dilution_timeline

    events = cache.capital_events(corp_code)
    items = dilution_timeline(events)
    if not items:
        return
    st.divider()
    st.markdown("#### 🕒 자본이벤트 타임라인 (증자·감자·CB/BW/EB·자기주식)")
    n_missing = sum(1 for it in items if it["shares_delta"] is None)
    render_dilution_timeline(items, key="dil_timeline")
    cap = ("▲증자 ▼감자 ◆잠재(CB/BW/EB) ●자기주식(총주식수 불변) · 점선=확정 발행주식 누적. "
           "잠재·자기주식은 누적에서 제외.")
    if n_missing:
        cap += f" · 주식수 미기재 {n_missing}건은 마커 생략(원본 필드 부재)."
    st.caption(cap)


def _fmt_peer_val(v, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v*100:.1f}%"
    if kind == "mult":
        return f"{v:.1f}x"
    return f"{v:.0f}"


def _peer_panel(corp_code: str) -> None:
    """섹터(KSIC 중분류) 피어 대비 지표 백분위 + 피어 목록."""
    pb = cache.peer_benchmark(corp_code)
    if not pb or not pb.get("has_sector"):
        st.info("업종코드가 없습니다. (수집: `python scripts/collect_industry.py --skip-existing`)")
        return
    if pb.get("insufficient"):
        st.info(f"**{pb['sector_name']}** 섹터 피어가 부족합니다 ({pb['n_peers']}개사).")
        return

    st.markdown(f"#### 🏢 {pb['sector_name']} — 피어 {pb['n_peers']}개사 대비 (최신 FY)")
    if pb.get("is_financial"):
        st.caption("ℹ️ 금융업(은행/보험/지주)은 이자수익 구조·고레버리지가 정상이라, 영업이익률·부채비율은 "
                   "일반 기준 평가에서 제외했습니다.")
    recs = []
    for m in pb["metrics"]:
        if m["value"] is None or m["percentile"] is None:
            recs.append({"지표": m["label"], "기업값": _fmt_peer_val(m["value"], m["kind"]),
                         "섹터중앙값": "—", "백분위": "—", "평가": "—"})
            continue
        good = m["percentile"] if m["higher_better"] else (100 - m["percentile"])
        verdict = "🟢 우수" if good >= 70 else "🔴 열위" if good <= 30 else "🟡 평균"
        recs.append({
            "지표": m["label"], "기업값": _fmt_peer_val(m["value"], m["kind"]),
            "섹터중앙값": _fmt_peer_val(m["median"], m["kind"]),
            "백분위": f"{m['percentile']:.0f}%", "평가": verdict,
        })
    st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")
    st.caption("백분위 = 섹터 내 위치(0=최저, 100=최고). 평가: 방향 반영(저 PER/부채=우수). "
               "섹터=KSIC 중분류(업종코드 앞 2자리).")

    st.markdown("**시총 상위 피어**")
    prows = [{
        "기업명": ("★ " if r["corp_code"] == corp_code else "") + r["corp_name"],
        "시총(조)": round(r.get("market_cap_jo") or 0, 2),
        "ROE": _fmt_peer_val(r.get("roe"), "pct"),
        "영업이익률": _fmt_peer_val(r.get("op_margin"), "pct"),
        "PER": _fmt_peer_val(r.get("per"), "mult"),
        "PBR": _fmt_peer_val(r.get("pbr"), "mult"),
    } for r in pb["peers"]]
    st.dataframe(pd.DataFrame(prows), hide_index=True, width="stretch")
    st.caption("⚠ PER·PBR·시총 = 각 사 **최신 거래일 종가** 기준입니다. 💰 밸류에이션 탭은 **FY말 종가** "
               "기준이라 같은 기업이라도 값이 다를 수 있습니다(주가 급변 구간일수록 괴리 큼).")


def _trust_badge(corp_code: str) -> None:
    """데이터 신뢰 배지 — Gate B(보고서==DB) 감사 결과를 한 줄로."""
    t = cache.trust_summary(corp_code)
    if not t or t["total"] == 0:
        return
    if t["fail_a"] > 0:
        st.error(f"⚠ 보고서 ≠ DB 확정 불일치 {t['fail_a']}건 (Gate B fail_a) — 값 확인 필요")
    elif t["fail"] > 0:
        st.warning(f"🔎 보고서↔DB 검토 대상 {t['fail']}건 (Gate B fail_b, 휴리스틱 항목)")
    else:
        tail = f" · 미검증 {t['pending']}" if t["pending"] else ""
        st.success(f"✅ 보고서↔DB 검증 통과 — Gate B pass **{t['pass']:,}** 기간 · 불일치 0{tail}",
                   icon="✅")
    _amendment_badge(corp_code)


def _amendment_badge(corp_code: str) -> None:
    """🔄 기재정정 이력 — 정정본 존재 기간 + DB 반영 여부(C9). as-filed 저장의 stale 리스크 투명화."""
    a = cache.amendment_summary(corp_code)
    if not a or a["n_amended"] == 0:
        return
    orig = a["n_original"]
    msg = (f"🔄 기재정정 이력 **{a['n_amended']}개 기간** — DB 정정본 반영 {a['n_reflects']}"
           + (f" · 원본유지 {orig}" if orig else ""))
    if orig:
        st.warning(msg + " (원본유지 = 지연·첨부정정 등으로 정정 내용 미반영 가능 → 원문 확인 권장)")
    else:
        st.caption(msg + " (모두 정정본 반영)")
    with st.expander(f"기재정정 기간 상세 ({a['n_amended']})", expanded=False):
        df = pd.DataFrame([{
            "연도": p["fiscal_year"], "기간": p["fiscal_period"],
            "DB 반영": "정정본" if p["uses_amend"] else "원본유지",
        } for p in a["periods"]])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("출처: DART [기재정정] 공시. reconcile 은 적시 기재정정(최초제출 +400일 내)을 "
                   "우선 채택하므로 대개 정정본이 반영됩니다. '원본유지'는 지연/첨부정정 등으로 "
                   "원본이 채택된 기간입니다.")


def _regulatory_panel(reg_status: dict) -> None:
    """⚠ 시장조치 이력 — 관리종목/상장폐지/매매정지 등. 활성 조치가 있으면 경고, 없으면 표시 안 함
    (이력 자체가 없는 기업이 대다수라 배지처럼 항상 노출하지 않고, 과거 이력만 있어도 접어서 제공)."""
    from app.data.regulatory import EVENT_LABELS

    events = reg_status["events"]
    if not events:
        return

    active = reg_status["active"]
    if active:
        labels = ", ".join(EVENT_LABELS.get(t, t) for t in active)
        st.error(f"⚠ 시장조치 이력 — 현재 활성: **{labels}**")
    else:
        st.caption("⚠ 시장조치 이력 있음(현재는 모두 해제됨) — 아래 펼쳐서 확인")

    with st.expander(f"시장조치 이력 상세 ({len(events)}건)", expanded=bool(active)):
        df = pd.DataFrame([{
            "일자": e["filed_at"],
            "구분": EVENT_LABELS.get(e["event_type"], e["event_type"]),
            "해제여부": "해제" if e["is_lift"] else "지정/발생",
            "공시명": e["report_nm"],
        } for e in events])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("출처: DART 거래소공시(pblntf_ty=I). 자세한 내용은 DART 원문 공시를 확인하세요.")


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


def _ownership_panel(corp_code: str) -> None:
    """대주주/지분 현황(B3) — 최대주주+특수관계인 지분, 소액주주(float 근사치), 변동이력."""
    yr, holders, retail, changes = cache.ownership_status(corp_code)
    if not holders:
        st.info("지분 데이터가 없습니다. (수집: `python scripts/collect_shareholders.py --corps "
                f"{corp_code} --year 2024`)")
        return
    st.markdown(f"#### 🏛 대주주/지분 현황 — {yr} 사업보고서")

    # DART 원본에 "계"(주식종류별 소계) 행이 포함돼 있음 — 있으면 그걸로 합계(중복합산 방지),
    # 없으면 개별 보유자 행을 직접 합산(폴백).
    total_rows = [h for h in holders if h["name"].strip() == "계" and h.get("pct_end") is not None]
    if total_rows:
        major_pct = sum(h["pct_end"] for h in total_rows)
    else:
        major_pct = sum(h["pct_end"] for h in holders if h.get("pct_end") is not None)
    c1, c2, c3 = st.columns(3)
    c1.metric("최대주주+특수관계인 지분율", f"{major_pct:.1f}%")
    if retail and retail.get("held_rate_pct") is not None:
        c2.metric("소액주주 지분율 (float 근사)", f"{retail['held_rate_pct']:.1f}%")
        c3.metric("소액주주 수", f"{retail.get('holder_count', 0):,}명 "
                  f"({retail.get('holder_rate_pct', 0):.1f}%)")
    else:
        c2.metric("소액주주 지분율", "—")

    df = pd.DataFrame([{
        "성명": h["name"], "관계": h.get("relation") or "—",
        "주식종류": h.get("stock_kind") or "—",
        "기말지분율(%)": h.get("pct_end"), "기말소유주식수": h.get("shares_end"),
        "비고": h.get("remark") or "—",
    } for h in holders])
    st.dataframe(df, hide_index=True, width="stretch")

    if changes:
        with st.expander(f"최대주주 변동이력 ({len(changes)}건)", expanded=False):
            df_chg = pd.DataFrame([{
                "변동일": c["change_on"], "변경 후 최대주주": c.get("holder_name") or "—",
                "지분율(%)": c.get("pct"), "변동원인": c.get("cause") or "—",
            } for c in changes])
            st.dataframe(df_chg, hide_index=True, width="stretch")

    st.caption("출처: DART 최대주주현황(hyslrSttus)·최대주주변동현황(hyslrChgSttus)·"
               "소액주주현황(mrhlSttus). 소액주주 지분율은 유통주식(float)의 근사치입니다.")


def _pctfmt(v, decimals: int = 1) -> str:
    """이미 % 스케일(예: 67.8)인 값 문자열화 — fmt_pct 는 소수(0.678)를 가정해 여기선 미사용."""
    return f"{v:.{decimals}f}%" if v is not None else "—"


def _shareholder_return_panel(corp_code: str, requested_stmt: str) -> None:
    """💸 주주환원 — DPS/배당성향/총주주환원율 추이 + 자사주 취득·처분 상세(Phase 2, PRD 13)."""
    import plotly.graph_objects as go

    rows = cache.shareholder_return(corp_code, requested_stmt)
    rows = [r for r in rows if r.get("dps_common") is not None or r.get("payout_ratio") is not None
            or r.get("total_shareholder_return_won") is not None]
    if not rows:
        st.info("배당·자기주식 데이터가 없습니다. (수집: `python scripts/collect_periodic_apis.py "
                f"--api alotMatter,tesstkAcqsDspsSttus --years 2015-2025 --corps {corp_code}`)")
        return

    rows = sorted(rows, key=lambda r: r["fiscal_year"])
    latest = rows[-1]
    st.markdown(f"#### 💸 주주환원 — {latest['fiscal_year']} FY 기준")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("주당 현금배당금(보통주)", f"{latest['dps_common']:,}원" if latest.get("dps_common") is not None else "—")
    c2.metric("현금배당수익률", _pctfmt(latest.get("dividend_yield_common")))
    c3.metric("배당성향", _pctfmt(latest.get("payout_ratio")))
    c4.metric("총주주환원율", _pctfmt(latest.get("total_shareholder_return_ratio")))

    years = [str(r["fiscal_year"]) for r in rows]
    fig = go.Figure()
    fig.add_bar(x=years, y=[r.get("dps_common") for r in rows], name="주당 현금배당금(원)")
    fig.add_trace(go.Scatter(x=years, y=[r.get("payout_ratio") for r in rows], name="배당성향(%)",
                             yaxis="y2", mode="lines+markers"))
    fig.add_trace(go.Scatter(x=years, y=[r.get("total_shareholder_return_ratio") for r in rows],
                             name="총주주환원율(%)", yaxis="y2", mode="lines+markers"))
    fig.update_layout(
        yaxis=dict(title="DPS(원)"), yaxis2=dict(title="%", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=380,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True, key="shr_return_chart")

    df = pd.DataFrame([{
        "연도": r["fiscal_year"],
        "DPS(보통주)": r.get("dps_common"), "DPS(우선주)": r.get("dps_pref"),
        "현금배당수익률(%)": r.get("dividend_yield_common"),
        "배당총액(억원)": (r["total_dividend_amount_won"] / EOK) if r.get("total_dividend_amount_won") is not None else None,
        "배당성향(%)": r.get("payout_ratio"),
        "자사주순취득(억원)": (r["buyback_amount_won"] / EOK) if r.get("buyback_amount_won") is not None else None,
        "총주주환원율(%)": r.get("total_shareholder_return_ratio"),
    } for r in reversed(rows)])
    render_dataframe(
        df,
        num_cols=["DPS(보통주)", "DPS(우선주)", "배당총액(억원)", "자사주순취득(억원)"],
        pct_cols=["현금배당수익률(%)", "배당성향(%)", "총주주환원율(%)"])

    detail = cache.treasury_activity_detail(corp_code, latest["fiscal_year"])
    totals = [d for d in detail if d.get("acqs_method3") == "총계"]
    if totals:
        with st.expander(f"자기주식 취득·처분 상세 ({latest['fiscal_year']} FY, 주식종류별 총계)", expanded=False):
            df_t = pd.DataFrame([{
                "주식종류": t.get("stock_kind") or "—", "기초수량": t.get("qty_begin"),
                "취득": t.get("qty_acquired"), "처분": t.get("qty_disposed"),
                "소각": t.get("qty_incinerated"), "기말수량": t.get("qty_end"),
                "비고": t.get("remark") or "—",
            } for t in totals])
            render_dataframe(df_t, num_cols=("기초수량", "취득", "처분", "소각", "기말수량"))

    st.caption("출처: DART 배당에관한사항(alotMatter)·자기주식취득및처분현황(tesstkAcqsDspsSttus). "
               "배당성향=공시값 우선(없으면 배당총액/지배주주순이익 재계산). 총주주환원율="
               "(배당총액+자사주 순취득금액)/지배주주순이익.")


def _employee_panel(corp_code: str) -> None:
    """직원 현황(부문×성별) — Phase 2, PRD 13 ④."""
    yr, rows = cache.employee_stats(corp_code)
    if not rows:
        st.info("직원 현황 데이터가 없습니다. (수집: `python scripts/collect_periodic_apis.py "
                f"--api empSttus --years 2023 --corps {corp_code}`)")
        return
    st.markdown(f"#### 👥 직원 현황 — {yr} 사업보고서")
    total_row = next((r for r in rows if r.get("division") == "성별합계"
                       and r.get("annual_salary_total") is not None), None)
    if total_row:
        total_headcount = sum(r["total_count"] or 0 for r in rows if r.get("division") == "성별합계")
        c1, c2, c3 = st.columns(3)
        c1.metric("전체 인원", f"{total_headcount:,}명")
        c2.metric("평균 근속연수(가중평균 아님, 성별 단순평균)",
                  f"{sum(r['avg_tenure_years'] or 0 for r in rows if r.get('division')=='성별합계')/2:.1f}년")
        avg_sal = [r["avg_salary"] for r in rows if r.get("division") == "성별합계" and r.get("avg_salary")]
        if avg_sal:
            c3.metric("1인평균급여(남/여 평균)", f"{sum(avg_sal)/len(avg_sal)/1e8:.2f}억원")
    df = pd.DataFrame([{
        "부문": r.get("division") or "—", "성별": r.get("sex") or "—",
        "정규직": r.get("regular_count"), "계약직": r.get("contract_count"),
        "합계": r.get("total_count"), "평균근속(년)": r.get("avg_tenure_years"),
        "연간급여총액(억원)": (r["annual_salary_total"] / EOK) if r.get("annual_salary_total") else None,
        "1인평균급여(원)": r.get("avg_salary"),
    } for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("출처: DART 직원현황(empSttus). 급여총액/1인평균은 부문 전체(성별합계) 행에만 공시됨.")


def _other_investment_panel(corp_code: str) -> None:
    """타법인 출자현황 — Phase 2, PRD 13 ④."""
    yr, rows = cache.other_investments(corp_code)
    if not rows:
        st.info("타법인 출자현황 데이터가 없습니다. (수집: `python scripts/collect_periodic_apis.py "
                f"--api otrCprInvstmntSttus --years 2023 --corps {corp_code}`)")
        return
    st.markdown(f"#### 🏢 타법인 출자현황 — {yr} 사업보고서 · {len(rows)}건")
    df = pd.DataFrame([{
        "법인명": r.get("investee_name") or "—", "출자목적": r.get("purpose") or "—",
        "최초취득일": r.get("first_acquired_date") or "—",
        "기말지분율(%)": r.get("end_pct"),
        "기말장부가액(억원)": (r["end_book_value"] / EOK) if r.get("end_book_value") is not None else None,
        "피출자법인 총자산(억원)": (r["investee_total_assets"] / EOK) if r.get("investee_total_assets") is not None else None,
        "피출자법인 순이익(억원)": (r["investee_net_income"] / EOK) if r.get("investee_net_income") is not None else None,
    } for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("출처: DART 타법인출자현황(otrCprInvstmntSttus).")


def _exec_pay_panel(corp_code: str) -> None:
    """임원보수(요약+개인별 5억이상 상위5인) — Phase 2, PRD 13 ④."""
    yr, summary, individuals = cache.exec_pay(corp_code)
    if not summary and not individuals:
        st.info("임원보수 데이터가 없습니다. (수집: `python scripts/collect_periodic_apis.py "
                f"--api hmvAuditAllSttus,indvdlByPay --years 2023 --corps {corp_code}`)")
        return
    st.markdown(f"#### 💼 임원보수 — {yr} 사업보고서")
    if summary:
        c1, c2, c3 = st.columns(3)
        c1.metric("이사·감사 인원", f"{summary.get('total_exec_count', '—')}명")
        c2.metric("보수총액", fmt_amount(summary.get("total_pay_amount")))
        c3.metric("1인평균보수", fmt_amount(summary.get("avg_pay_per_person")))
    if individuals:
        with st.expander(f"개인별 보수 5억원 이상 (상위 {len(individuals)}인)", expanded=False):
            df = pd.DataFrame([{
                "성명": i.get("person_name") or "—", "직위": i.get("position") or "—",
                "보수총액(억원)": (i["total_pay_amount"] / EOK) if i.get("total_pay_amount") is not None else None,
            } for i in individuals])
            st.dataframe(df, hide_index=True, width="stretch")
    st.caption("출처: DART 이사·감사 전체보수현황(hmvAuditAllSttus)·개인별보수지급금액"
               "(indvdlByPay, 미등기 고문/상담역 포함 가능).")


def _production_panel(corp_code: str) -> None:
    """생산능력/생산실적/가동률(B4) — 사업보고서 본문표에서 파싱한 부문·품목별 시계열."""
    import plotly.graph_objects as go
    from app.data import biz as _biz

    data = cache.biz_production(corp_code)
    if not data.get("available"):
        st.info("생산 데이터가 없습니다. 제조·자원 업종이 아니거나 아직 수집되지 않았습니다. "
                f"(수집: `python scripts/collect_biz_metrics.py --corps {corp_code} --latest`)")
        return
    rows, years, ry = data["rows"], data["years"], data["report_year"]
    st.markdown(f"#### 🏭 생산능력·생산실적·가동률 — {ry} 사업보고서 기준")

    # ── 가동률 추이(공통 단위 %라 한 차트에) ──
    util = _biz.utilization_series(rows)
    if util:
        latest = [(lbl, pts[-1][1]) for lbl, pts in util if pts]
        if latest:
            cols = st.columns(min(len(latest), 4))
            for (lbl, v), col in zip(latest[:4], cols):
                col.metric(f"가동률 · {lbl[:16]}", f"{v:.1f}%")
        fig = go.Figure()
        for lbl, pts in util:
            fig.add_trace(go.Scatter(
                x=[y for y, _ in pts], y=[v for _, v in pts], mode="lines+markers", name=lbl))
        fig.update_layout(
            title="가동률 추이 (%)", height=340, margin=dict(t=40, b=10, l=10, r=10),
            yaxis_title="가동률(%)", xaxis=dict(dtick=1),
            legend=dict(orientation="h", yanchor="bottom", y=-0.35))
        st.plotly_chart(fig, use_container_width=True, key="biz_util")
    else:
        st.caption("가동률 시계열 데이터가 없습니다.")

    # ── 생산능력/생산실적 표(부문·품목별, 단위 상이라 표로) ──
    for metric in ("capacity", "output"):
        recs = _biz.production_table(rows, metric, years)
        if not recs:
            continue
        df = pd.DataFrame(recs)
        year_cols = [str(y) for y in years if str(y) in df.columns]
        df = df[["부문·품목", "단위"] + year_cols]
        st.markdown(f"**{_biz.METRIC_LABELS[metric]}** (부문·품목별)")
        render_dataframe(df, num_cols=year_cols)

    # ── 비시계열 보조표(표준생산능력·가동가능일수 등) ──
    supp = _biz.supplementary_rows(rows)
    if supp:
        with st.expander(f"생산설비 보조지표 ({len(supp)}건)", expanded=False):
            st.dataframe(pd.DataFrame(supp), hide_index=True, width="stretch")

    st.caption("출처: DART 정기(사업)보고서 'II. 사업의 내용' 본문 생산능력/생산실적/가동률 표. "
               "부문·품목마다 단위가 다를 수 있어 가동률(%)만 함께 그리고, 생산능력/실적은 표로 "
               "표시합니다. 가동률이 100%를 넘는 값은 초과가동(교대·잔업)으로 보고서 원값 그대로입니다.")

    st.divider()
    _sales_panel(corp_code)

    st.divider()
    _order_backlog_panel(corp_code)


def _sales_panel(corp_code: str) -> None:
    """부문·수출/내수 매출 구성(Phase 3) — 부문별 매출 스택 막대 + 수출비중(%) 라인.
    한 기업의 여러 매출표(부문별/제품별/지역별) 중 최신 보고서에서 부문 구성용·수출비중용 표를
    각각 단일 선택(app.data.biz.load_sales_composition)해 중복합산을 피한다."""
    import plotly.graph_objects as go

    data = cache.sales_composition(corp_code)
    if not data.get("available"):
        st.caption("🧾 부문·수출/내수 매출 데이터가 없습니다. (사업보고서 본문에 매출실적 표가 없거나 "
                   f"아직 미수집 — 수집: `python scripts/collect_sales_metrics.py --corps {corp_code} --latest`)")
        return

    unit = data.get("unit") or "원문 단위"
    st.markdown(f"#### 🧾 부문·수출/내수 매출 — {data['report_year']} 사업보고서 기준")

    seg_rows, years = data["segment_rows"], data["years"]
    if seg_rows:
        # 부문별 매출 스택 막대(연도별) — 상위 8개 부문·품목만(가독성).
        top = seg_rows[:8]
        fig = go.Figure()
        for s in top:
            fig.add_bar(name=s["label"][:28],
                        x=[str(y) for y in years],
                        y=[s["by_year"].get(y) for y in years])
        fig.update_layout(
            barmode="stack", height=380, margin=dict(t=30, b=10, l=10, r=10),
            yaxis_title=f"매출액({unit})", xaxis=dict(dtick=1),
            legend=dict(orientation="h", yanchor="bottom", y=-0.4))
        st.plotly_chart(fig, use_container_width=True, key="sales_stack")

        df = pd.DataFrame([{"부문·품목": s["label"],
                            **{str(y): s["by_year"].get(y) for y in years}} for s in seg_rows])
        render_dataframe(df, num_cols=[str(y) for y in years])
        st.caption(f"부문별 매출 구성 (단위: {unit}) · 스택 막대는 상위 8개 부문·품목")

    exp_rows = data["export_rows"]
    if exp_rows:
        latest = exp_rows[-1]
        if latest.get("ratio_pct") is not None:
            st.metric(f"수출비중 ({latest['year']})", f"{latest['ratio_pct']:.1f}%")
        fig2 = go.Figure()
        fig2.add_bar(name="내수", x=[str(e["year"]) for e in exp_rows],
                     y=[e["domestic"] for e in exp_rows])
        fig2.add_bar(name="수출", x=[str(e["year"]) for e in exp_rows],
                     y=[e["export"] for e in exp_rows])
        fig2.add_trace(go.Scatter(
            name="수출비중(%)", x=[str(e["year"]) for e in exp_rows],
            y=[e["ratio_pct"] for e in exp_rows], yaxis="y2", mode="lines+markers"))
        fig2.update_layout(
            barmode="stack", height=340, margin=dict(t=30, b=10, l=10, r=10),
            yaxis=dict(title=f"매출액({unit})"),
            yaxis2=dict(title="수출비중(%)", overlaying="y", side="right", range=[0, 100]),
            xaxis=dict(dtick=1),
            legend=dict(orientation="h", yanchor="bottom", y=-0.3))
        st.plotly_chart(fig2, use_container_width=True, key="sales_export")

    st.caption("출처: DART 사업보고서 'II. 사업의 내용' 매출실적/판매실적 본문표. 한 회사가 부문별·"
               "제품별·지역별 표를 함께 공시하는 경우 부문 구성은 부문 수가 가장 많은 표, 수출비중은 "
               "수출·내수 구분 표를 각각 선택합니다(표마다 매출을 다른 축으로 재분해하므로 합산 주의).")


def _order_backlog_panel(corp_code: str) -> None:
    """수주상황(수주잔고) — 건설/조선/방산 등 수주 기반 업종. 사업보고서 본문표 파싱(B1→B4)."""
    data = cache.order_backlog(corp_code)
    if not data.get("available"):
        st.caption("🏗 수주상황 데이터가 없습니다. (수주 기반 업종이 아니거나, 계약잔액 없이 "
                   "진행률%만 공시하는 표 형식이라 v1 범위 밖이거나, 아직 미수집)")
        return
    rows = data["rows"]
    st.markdown(f"#### 🏗 수주상황 — {data['fiscal_year']} 사업보고서 기준")

    # 다년 수주잔고 추이(2개 연도 이상 보유 시)
    trend = cache.order_backlog_trend(corp_code)
    if trend.get("available"):
        from app.views.chart_panel import render_backlog_trend
        pts = trend["points"]
        first, last = pts[0], pts[-1]
        if first["backlog"]:
            chg = (last["backlog"] / first["backlog"] - 1) * 100
            st.caption(f"수주잔고 {first['year']}→{last['year']}: **{chg:+.0f}%** "
                       f"({len(pts)}개 연도)")
        render_backlog_trend(pts, trend.get("unit"), key="backlog_trend")

    df = pd.DataFrame([{
        "구분": r["category"] or "전체", "수주총액": r["new_orders"],
        "기납품액": r["completed"], "수주잔고": r["backlog_amt"],
    } for r in rows])
    render_dataframe(df, num_cols=("수주총액", "기납품액", "수주잔고"))
    st.caption("출처: DART 사업보고서 '수주상황'/'수주계약 현황' 본문표. 단위는 원문 그대로(보통 "
               "백만원). 프로젝트별 상세 공시는 회사 전체 합계로 축약했습니다.")


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


def _tearsheet_download(corp_code: str, meta: dict, stmt: str) -> None:
    """📄 요약 tearsheet(PDF) — 생성 비용(matplotlib) 지연: 버튼 클릭 시에만 생성 후 다운로드 노출."""
    st.divider()
    if st.button("📄 요약 tearsheet PDF 생성", key=f"ts_gen_{corp_code}",
                 help="밸류에이션·재무·수익성 요약 + 추이 차트를 한 페이지 PDF 로."):
        st.session_state["ts_ready"] = corp_code
    if st.session_state.get("ts_ready") == corp_code:
        pdf = cache.tearsheet_pdf(corp_code, stmt)
        if pdf:
            st.download_button(
                "⬇ tearsheet PDF 내려받기", data=pdf,
                file_name=f"{meta['corp_name']}_{corp_code}_tearsheet.pdf",
                mime="application/pdf", key=f"ts_dl_{corp_code}", width="content")
        else:
            st.info("요약을 생성할 재무 데이터가 부족합니다.")


def _watch_toggle(container, corp_code: str) -> None:
    """⭐ 관심종목 추가/해제 토글(사이드바 관심종목 목록과 연동)."""
    from app.data import watchlist as wl

    watched = wl.is_watched(corp_code)
    label = "⭐ 관심해제" if watched else "☆ 관심추가"
    if container.button(label, key=f"wl_toggle_{corp_code}", width="stretch",
                        help="좌측 사이드바 ⭐ 관심종목에서 빠르게 다시 열 수 있습니다."):
        wl.toggle(corp_code)
        st.rerun()


def _source_drilldown(corp_code: str, used_stmt: str) -> None:
    """🔗 원천 공시 드릴다운 — 표시 재무의 BS/IS/CF 가 어느 filing 에서 왔는지 DART 링크(D2b)."""
    sources = cache.statement_sources(corp_code, used_stmt, "FY")
    if not sources:
        return
    with st.expander("🔗 이 값의 원천 공시 (연도별 BS/IS/CF source filing)", expanded=False):
        st.caption("표준화된 재무 값은 재무제표(BS/IS/CF)별로 단일 공시에서 조립됩니다. "
                   "부분 기재정정이 있으면 표별로 원천 공시가 다를 수 있어 아래에 나눠 표시합니다.")
        for fy in sorted(sources.keys(), reverse=True)[:12]:
            items = sources[fy]
            st.markdown(f"**{fy}**")
            cols = st.columns(len(items))
            for col, it in zip(cols, items):
                stmts = "·".join(it["statements"])
                col.link_button(f"{stmts} · {it['rcept_no']} ↗", it["dart_url"],
                                width="stretch")


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


def render(corp_code: str | None = None) -> None:
    """corp_code 를 명시하면 그 기업을 그리고, 생략하면 전역 focus_corp 를 따른다
    (스크리너 등 독립된 화면에서 자체 선택 기업을 넘겨 전역 상태와 분리하기 위함)."""
    st.header("기업 시각화")

    if corp_code is None:
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

    reg_status = cache.regulatory_status(corp_code)
    notes = corp_notes(fiscal_month=meta.get("fiscal_month"),
                       used_stmt=used_stmt, requested_stmt=requested_stmt,
                       has_regulatory_flag=bool(reg_status["active"]))
    hcol, scol = st.columns([5, 1])
    hcol.subheader(fmt_corp_identity(
        meta["corp_name"], meta["corp_code"], meta.get("stock_code"),
        meta.get("market")) + fmt_notes(notes))
    _watch_toggle(scol, corp_code)
    if notes:
        st.caption("기업명 옆 **(주n)** 표시의 뜻은 좌측 메뉴 **ℹ️ 도움말** 페이지를 참고하세요.")

    _report_viewer(corp_code)
    _trust_badge(corp_code)
    _regulatory_panel(reg_status)

    if not series:
        st.warning(f"{'분기' if grain=='quarter' else '연간'} 표준화 재무제표 데이터가 없습니다.")
        return
    if used_stmt != requested_stmt:
        st.caption(f"※ {'연결' if requested_stmt=='consolidated' else '별도'} 데이터 없음 "
                   f"→ {'연결' if used_stmt=='consolidated' else '별도'} 표시")

    _dq_banner(series, grain)

    # 이상치 가드 — DB 는 보고서와 일치(Gate B)하나 소스 자체가 비정상일 수 있어 표시단계에서 플래그.
    # 금융업(은행/보험/지주)은 영업이익률 sanity 를 적용하지 않는다(이자수익 구조 — 안내 표시).
    from analyzer.ksic import is_financial_sector
    from app.compute.checks import financial_anomalies
    induty = meta.get("induty_code")
    if is_financial_sector(induty):
        st.caption("ℹ️ 금융업(은행/보험/지주)은 업 특성상 일반 제조업 기준(영업이익률·부채비율)을 "
                   "이상치·섹터 평가에 적용하지 않습니다.")
    anomalies = financial_anomalies(series, grain, induty_code=induty)
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
            "📈 주가", "📊 주가·재무 결합", "🏭 생산·매출", "🏢 섹터·피어", "👔 임원·지분",
            "💸 주주환원"]
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
        _source_drilldown(corp_code, used_stmt)
        _tearsheet_download(corp_code, meta, requested_stmt)

    # ── 지표 (레지스트리 멀티셀렉트 + 그래프/표) ──
    elif active == TABS[1]:
        # 지표 탭은 전체 기간 사용(표=전체 표시, 그래프=슬라이더로 기간 조절)
        if grain == "quarter":
            mseries, _ = cache.quarter_series(corp_code, requested_stmt, quarters=400)
        else:
            mseries, _ = cache.annual_series(corp_code, requested_stmt, years=200)
        metric_panel.render(mseries, grain, meta["corp_name"], corp_code)

    # ── 밸류에이션 (연간 FY / 분기 TTM 선택) ──
    elif active == TABS[2]:
        basis = st.radio("멀티플 기준", ["연간(FY)", "분기(TTM)"], horizontal=True,
                         key="val_basis", label_visibility="collapsed")
        is_ttm = basis == "분기(TTM)"
        mv = (cache.company_multiples_ttm(corp_code, requested_stmt) if is_ttm
              else cache.company_multiples(corp_code, requested_stmt))
        if not mv or not mv.get("market_cap"):
            if is_ttm:
                st.info("직전 4개 분기 데이터가 부족해 TTM 멀티플을 계산할 수 없습니다. (연간 기준을 이용하세요)")
            else:
                st.info("주가/시총 데이터가 없어 밸류에이션을 계산할 수 없습니다.")
        else:
            stmt_ko = '연결' if mv.get('used_stmt') == 'consolidated' else '별도'
            pdate = mv.get("price_date")
            if is_ttm:
                st.markdown(f"**TTM {mv.get('ttm_end', '')} 기준** · {stmt_ko} · 직전 4분기 합산")
                st.caption(f"주가 기준일: **{pdate}** (현재가) · 손익·현금흐름은 직전 4분기 합산, "
                           f"재무상태·주식수는 최신 분기 스냅샷"
                           if pdate else "주가 기준일: — (주가 데이터 없음)")
            else:
                st.markdown(f"**{mv.get('fiscal_year')} FY 기준** · {stmt_ko}")
                st.caption(f"주가 기준일: **{pdate}** (해당 FY 말 근처 종가) · 시총·PER·PBR 은 이 종가 기준"
                           if pdate else "주가 기준일: — (주가 데이터 없음)")
            st.dataframe(_valuation_df(mv), width="stretch")

        _valuation_bands(corp_code)
        _per_share_trends(corp_code, requested_stmt)
        _dilution_timeline(corp_code)

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

    # ── 생산·가동률 (B4) ──
    elif active == TABS[6]:
        _production_panel(corp_code)

    # ── 섹터·피어 벤치마킹 ──
    elif active == TABS[7]:
        _peer_panel(corp_code)

    # ── 임원·지분 (지배구조) ──
    elif active == TABS[8]:
        _executives_panel(corp_code)
        st.divider()
        _ownership_panel(corp_code)
        st.divider()
        _exec_pay_panel(corp_code)
        st.divider()
        _employee_panel(corp_code)
        st.divider()
        _other_investment_panel(corp_code)

    # ── 주주환원 (배당·자기주식, Phase 2) ──
    elif active == TABS[9]:
        _shareholder_return_panel(corp_code, requested_stmt)
