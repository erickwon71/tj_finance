"""
분기 변화 페이지 — 전 대상기업의 매출·영업이익 QoQ/YoY 증감(액·률).

연도 선택 + Q1~Q4 탭. 탭을 고르면 해당 (달력연도, 분기)의 전 대상기업 표를 보여준다.
데이터 없는 분기는 빈 표, 있으면 데이터 있는 기업만. 상단에 '표시 N / 전체 M'.
증감률 등 수치 컬럼은 표 헤더 클릭으로 정렬 가능(숫자 정렬).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyzer.ratio_engine import _growth_rate
from app import cache, state
from app.components.export import to_csv_bytes
from app.format import corp_notes, fmt_corp_identity, fmt_notes
from app.views import company_page

_MODAL_QUARTERS = 16  # 모달 분기 추이에 표시할 최근 달력분기 수

# (calendar_period, 표시 라벨)
_Q_TABS: list[tuple[str, str]] = [("CQ1", "Q1"), ("CQ2", "Q2"), ("CQ3", "Q3"), ("CQ4", "Q4")]

_EOK = 1e8  # 억원

# 표시 컬럼(순서) + 숫자 포맷. 금액=억원, 비율=%.
_AMT_COLS = [
    "매출(억)", "매출 QoQ 증감(억)", "매출 YoY 증감(억)",
    "영업이익(억)", "영업이익 QoQ 증감(억)", "영업이익 YoY 증감(억)",
]
_PCT_COLS = [
    "매출 QoQ 증감률(%)", "매출 YoY 증감률(%)",
    "영업이익 QoQ 증감률(%)", "영업이익 YoY 증감률(%)",
]
_SORT_DEFAULT = "매출 YoY 증감률(%)"

_ALL_COLS = [
    "기업명", "종목코드", "시장", "기준",
    "매출(억)", "매출 QoQ 증감(억)", "매출 QoQ 증감률(%)",
    "매출 YoY 증감(억)", "매출 YoY 증감률(%)",
    "영업이익(억)", "영업이익 QoQ 증감(억)", "영업이익 QoQ 증감률(%)",
    "영업이익 YoY 증감(억)", "영업이익 YoY 증감률(%)",
]


def _eok(v):
    # 억원 정수 반올림(표시·정렬용). None 보존.
    return round(v / _EOK) if v is not None else None


def _pct(v):
    return (v * 100.0) if v is not None else None


def _to_display(rows: list[dict], requested_stmt: str) -> pd.DataFrame:
    recs = []
    for r in rows:
        # 기업명 옆 특별조치 각주: 주1=비-12월 결산(달력 재구성), 주2=연결→별도 대체.
        notes = corp_notes(fiscal_month=r.get("fiscal_month"),
                           used_stmt=r.get("used_stmt"), requested_stmt=requested_stmt)
        recs.append({
            "기업명": r["corp_name"] + fmt_notes(notes),
            "종목코드": r.get("stock_code") or "—",
            "시장": r.get("market") or "—",
            "기준": {"consolidated": "연결", "separate": "별도"}.get(r.get("used_stmt"), "—"),
            "매출(억)": _eok(r["revenue"]),
            "매출 QoQ 증감(억)": _eok(r["rev_qoq_amt"]),
            "매출 QoQ 증감률(%)": _pct(r["rev_qoq_pct"]),
            "매출 YoY 증감(억)": _eok(r["rev_yoy_amt"]),
            "매출 YoY 증감률(%)": _pct(r["rev_yoy_pct"]),
            "영업이익(억)": _eok(r["op"]),
            "영업이익 QoQ 증감(억)": _eok(r["op_qoq_amt"]),
            "영업이익 QoQ 증감률(%)": _pct(r["op_qoq_pct"]),
            "영업이익 YoY 증감(억)": _eok(r["op_yoy_amt"]),
            "영업이익 YoY 증감률(%)": _pct(r["op_yoy_pct"]),
            "corp_code": r["corp_code"],
        })
    df = pd.DataFrame(recs, columns=_ALL_COLS + ["corp_code"])
    return df


def _column_config() -> dict:
    # 금액=억원 천단위 구분(localized 프리셋; sprintf.js 는 '%,.0f' 미지원).
    # 비율=소수 1자리 %(printf; '%%' 는 리터럴 %).
    cfg = {c: st.column_config.NumberColumn(c, format="localized") for c in _AMT_COLS}
    cfg.update({c: st.column_config.NumberColumn(c, format="%.1f%%") for c in _PCT_COLS})
    cfg["corp_code"] = None  # 숨김
    return cfg


def _qlabel(r: dict) -> str:
    return f"{r['calendar_year']} {r['calendar_period']}"


def _modal_table(series: list[dict]) -> pd.DataFrame:
    """최근 분기(최신→과거)의 매출·영업이익 + QoQ(직전분기)·YoY(4분기전) 증감률."""
    recs = []
    for i, r in enumerate(series):
        qoq = series[i + 1] if i + 1 < len(series) else None   # 직전분기
        yoy = series[i + 4] if i + 4 < len(series) else None   # 전년동기
        rev, op = r.get("revenue"), r.get("operating_income")
        recs.append({
            "분기": _qlabel(r),
            "매출(억)": _eok(rev),
            "매출 QoQ%": _pct(_growth_rate(rev, qoq.get("revenue") if qoq else None)),
            "매출 YoY%": _pct(_growth_rate(rev, yoy.get("revenue") if yoy else None)),
            "영업이익(억)": _eok(op),
            "영업이익 QoQ%": _pct(_growth_rate(op, qoq.get("operating_income") if qoq else None)),
            "영업이익 YoY%": _pct(_growth_rate(op, yoy.get("operating_income") if yoy else None)),
        })
    return pd.DataFrame(recs)


def _modal_colcfg() -> dict:
    amt = ["매출(억)", "영업이익(억)"]
    pct = ["매출 QoQ%", "매출 YoY%", "영업이익 QoQ%", "영업이익 YoY%"]
    cfg = {c: st.column_config.NumberColumn(c, format="localized") for c in amt}
    cfg.update({c: st.column_config.NumberColumn(c, format="%.1f%%") for c in pct})
    return cfg


def _modal_chart(series: list[dict]) -> go.Figure:
    """매출·영업이익 분기 추이(그룹 막대, 억원). 과거→최신 순 x축."""
    chrono = list(reversed(series))
    x = [_qlabel(r) for r in chrono]
    rev = [(r.get("revenue") or 0) / _EOK for r in chrono]
    op = [(r.get("operating_income") or 0) / _EOK for r in chrono]
    fig = go.Figure()
    fig.add_bar(x=x, y=rev, name="매출")
    fig.add_bar(x=x, y=op, name="영업이익")
    fig.update_layout(
        barmode="group", height=380, margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="억원", legend=dict(orientation="h", y=1.1),
    )
    return fig


def _on_dialog_dismiss() -> None:
    """모달 닫을 때 원본 표의 행 선택을 초기화 → 같은 기업 재선택 시에도 다시 열림."""
    dfk = st.session_state.pop("qc_active_df", None)
    if dfk:
        try:
            del st.session_state[dfk]        # st.dataframe 선택 상태 리셋
        except Exception:  # noqa: BLE001
            pass


@st.dialog("기업 분기 시각화", width="large", on_dismiss=_on_dialog_dismiss)
def _viz_dialog(corp_code: str) -> None:
    """행 선택 시 **분기 기준** 시각화를 모달로 표시(표 레이아웃 안 밀림).
    매출·영업이익 분기 추이를 표/그래프로 선택. 전체 상세(주가·지표·밸류·대가)는 옵션.
    corp_code 는 파라미터로만 흘러가고 전역 focus_corp 는 건드리지 않는다 — 메인 메뉴
    "기업 시각화"·스크리너와 선택 상태를 완전히 분리하기 위함."""
    meta = cache.resolve_corp(corp_code)
    stmt = state.get_stmt_type()
    series, used = cache.quarter_series(corp_code, stmt, quarters=_MODAL_QUARTERS)
    if meta:
        notes = corp_notes(fiscal_month=meta.get("fiscal_month"),
                           used_stmt=used, requested_stmt=stmt)
        st.subheader(fmt_corp_identity(
            meta["corp_name"], meta["corp_code"], meta.get("stock_code"),
            meta.get("market")) + fmt_notes(notes))
    if not series:
        st.info("분기(달력분기) 데이터가 없습니다.")
        return
    used_ko = "연결" if used == "consolidated" else "별도"
    if used != stmt:
        st.caption(f"※ {'연결' if stmt=='consolidated' else '별도'} 분기 데이터 없음 → {used_ko} 표시")
    st.caption(f"최근 {len(series)}개 달력분기 · 매출·영업이익 · {used_ko} 기준")

    view = st.radio("보기", ["표", "그래프"], horizontal=True,
                    key=f"qc_modal_view_{corp_code}", label_visibility="collapsed")
    if view == "그래프":
        st.plotly_chart(_modal_chart(series), use_container_width=True,
                        key=f"qc_modal_chart_{corp_code}")
    else:
        st.dataframe(_modal_table(series), hide_index=True, width="stretch",
                     column_config=_modal_colcfg())

    # 전체 상세(주가·지표·밸류·대가) — 옵션(기본 접힘, 켤 때만 렌더 → 모달 가벼움). 분기 grain 강제.
    if st.toggle("전체 상세 분석 보기 (주가·지표·밸류·대가)", value=False,
                 key=f"qc_modal_full_{corp_code}"):
        saved_grain = state.get_grain()
        st.session_state[state.GRAIN] = "quarter"
        try:
            company_page.render(corp_code)
        finally:
            st.session_state[state.GRAIN] = saved_grain


def _render_quarter(cal_year: int, quarter: str, stmt: str) -> None:
    rows, total = cache.quarter_change(cal_year, quarter, stmt)

    stmt_ko = state.STMT_LABELS_INV.get(stmt, "연결")
    st.markdown(f"표시 **{len(rows):,}** / 전체 **{total:,}** 기업 · {cal_year} {quarter} · {stmt_ko} 기준")

    df = _to_display(rows, stmt)
    if df.empty:
        st.info("해당 분기 데이터가 없습니다.")
        # 빈 표(헤더만) 표시
        st.dataframe(df, hide_index=True, width="stretch", column_config=_column_config())
        return

    # 기본 정렬: 매출 YoY 증감률 내림차순(결측 뒤). 헤더 클릭으로 재정렬 가능.
    df = df.sort_values(_SORT_DEFAULT, ascending=False, na_position="last").reset_index(drop=True)

    event = st.dataframe(
        df, hide_index=True, width="stretch", column_config=_column_config(),
        on_select="rerun", selection_mode="single-row", key=f"qc_{cal_year}_{quarter}")
    sel = event.selection.rows if event and event.selection else []
    guard = f"qc_dlg_last_{cal_year}_{quarter}"
    if sel:
        cc = df.iloc[sel[0]]["corp_code"]
        # 선택 corp 이 바뀔 때만 모달 오픈(닫은 직후 selection 잔존 시 즉시 재오픈 방지).
        # 닫을 때 on_dismiss 가 이 표의 선택을 초기화 → sel 이 비면 아래서 guard 도 해제되어
        # 같은 기업을 다시 클릭해도 재오픈된다.
        if st.session_state.get(guard) != cc:
            st.session_state[guard] = cc
            st.session_state["qc_active_df"] = f"qc_{cal_year}_{quarter}"
            _viz_dialog(cc)
    else:
        st.session_state.pop(guard, None)

    st.download_button(
        "결과 CSV 내려받기", data=to_csv_bytes(df.drop(columns=["corp_code"]), index=False),
        file_name=f"quarter_change_{cal_year}_{quarter}.csv", mime="text/csv",
        key=f"qc_dl_{cal_year}_{quarter}")


def render() -> None:
    st.header("📊 분기 변화 — 매출·영업이익")
    st.caption("전 대상기업의 매출·영업이익을 **직전분기(QoQ)·전년동기(YoY)** 대비 증감액·증감률로 표시. "
               "증감률 등 숫자 컬럼은 헤더를 클릭해 정렬, **행을 클릭하면 팝업으로 해당 기업 시각화**가 뜹니다. "
               "기업명 옆 **(주1)(주2)** 표시의 뜻은 좌측 메뉴 **ℹ️ 도움말** 페이지를 참고하세요.")

    stmt = state.get_stmt_type()
    years = cache.quarter_change_years(stmt)
    if not years:
        st.warning("분기(달력분기) 데이터가 없습니다.")
        return

    cal_year = int(st.selectbox("달력연도", years, index=0, key="qc_year"))

    tabs = st.tabs([lbl for _, lbl in _Q_TABS])
    for (period, _), tab in zip(_Q_TABS, tabs):
        with tab:
            _render_quarter(cal_year, period, stmt)
