"""
Screener 페이지 — Phase 4(윈도우 집계 + 퀀트 다단계 + 비파괴 분할 시각화).

좌(필터·결과) · 우(선택기업 시각화)로 분할(`st.columns([5,7])`). 좌측에서 윈도우
집계(average/CAGR/YoY, 최대 10년)와 ≤3개 퀀트 패스(filter→sort→limit)를 구성·실행하고,
결과 행을 클릭하면 우측에 PRD 05 `company_page` 패널을 재사용해 시각화한다(좌측 결과는 유지).

수치·집계·필터는 기존 엔진 재사용 → `run.py screen` / `analyze` 와 정합:
- `app.compute.screen_eval`(=ratio_engine `_cagr`/`_growth_rate`·screener `_check`)
- `app.cache.screen_base_frame`(윈도우 로드+집계 1회 캐시)
- `app.views.company_page`(우측 패널)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import cache, state
from app.compute import screen_eval as se
from app.components.export import to_csv_bytes
from app.registry.metrics import METRIC_REGISTRY
from app.registry.units import UnitType
from app.views import company_page

# ── 필드 카탈로그(필터/정렬 가능) ──────────────────────────────
ALL_FIELD_IDS: list[str] = se.WINDOW_METRIC_IDS + se.MULTIPLE_IDS + [se.MARKET_CAP_ID]

_LABELS: dict[str, str] = {m.id: m.name_ko for m in METRIC_REGISTRY}
_LABELS.update(dict(se.MULTIPLE_FIELDS))
_LABELS[se.MARKET_CAP_ID] = "시가총액(조)"

_OPS = [">", ">=", "<", "<=", "="]
_RESULT_META = "screen_meta"   # session_state: {"df", "method", "cols", "counts"}


def _label(mid: str) -> str:
    return _LABELS.get(mid, mid)


def _windowable(mid: str) -> bool:
    """윈도우 집계 대상 여부(멀티플·시총은 최신 점값)."""
    return mid in se.WINDOW_METRIC_IDS


# ── 셀 포맷 ────────────────────────────────────────────────────
def _fmt(mid: str, method: str, value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if mid == se.MARKET_CAP_ID:
        return f"{value:.2f}조"
    unit = se.effective_unit(mid, method)
    if unit == UnitType.PCT:
        return f"{value * 100:.1f}%"
    if unit == UnitType.AMOUNT_EOK:
        return f"{value / se.EOK:,.0f}억"
    if unit == UnitType.MULTIPLE_X:
        return f"{value:.2f}x"
    if unit == UnitType.DAYS:
        return f"{value:.0f}일"
    return f"{value:.2f}"


# ── 퀀트 패스 UI ───────────────────────────────────────────────
def _pass_controls(i: int, method: str) -> dict:
    """패스 i 컨트롤 렌더 → {filters, sort_by, asc, limit}. 위젯 state 는 key 로 유지."""
    metrics = st.multiselect(
        f"필터 지표 (패스 {i + 1})", ALL_FIELD_IDS, format_func=_label,
        default=(["roe"] if i == 0 else []), key=f"p{i}_metrics")

    filters: dict[str, tuple[str, float]] = {}
    for mid in metrics:
        c1, c2 = st.columns([1, 2])
        unit = se.effective_unit(mid, method)
        default_op = "<" if (unit == UnitType.MULTIPLE_X and mid in se.MULTIPLE_IDS) else ">"
        with c1:
            op = st.selectbox(_label(mid), _OPS, index=_OPS.index(default_op),
                              key=f"p{i}_op_{mid}")
        with c2:
            suffix = {UnitType.PCT: " (%)", UnitType.AMOUNT_EOK: " (억원)",
                      UnitType.DAYS: " (일)"}.get(unit, "")
            if mid == se.MARKET_CAP_ID:
                suffix = " (조)"
            val = st.number_input(f"값{suffix}", value=10.0, step=1.0,
                                  key=f"p{i}_val_{mid}")
        filters[mid] = se.make_threshold(mid, method, op, val)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        sort_by = st.selectbox(f"정렬 (패스 {i + 1})", ALL_FIELD_IDS, format_func=_label,
                               key=f"p{i}_sort")
    with c2:
        order = st.selectbox("방향", ["내림", "오름"], key=f"p{i}_order")
    with c3:
        limit = int(st.number_input("한도", value=30, min_value=1, max_value=2000,
                                    step=10, key=f"p{i}_limit"))
    return {"filters": filters, "sort_by": sort_by, "asc": order == "오름", "limit": limit}


def _displayed_cols(passes: list[dict]) -> list[str]:
    """결과표에 보일 지표 = 모든 패스의 필터·정렬 키 합집합 + 시총."""
    cols: list[str] = []
    for p in passes:
        for k in list(p["filters"].keys()) + [p["sort_by"]]:
            if k and k not in cols:
                cols.append(k)
    if se.MARKET_CAP_ID not in cols:
        cols.append(se.MARKET_CAP_ID)
    return cols


# ── 좌측: 컨트롤 + 결과 ─────────────────────────────────────────
def _left() -> None:
    st.header("🔎 스크리너")
    method_label = {"average": "평균", "CAGR": "CAGR", "YoY": "YoY"}

    c1, c2 = st.columns([1, 1])
    with c1:
        n_years = int(st.slider("집계 기간(년)", 1, 10, 3, key="scr_n"))
    with c2:
        method = st.selectbox("집계 방법", se.AGG_METHODS,
                              format_func=lambda m: method_label[m], key="scr_method")
    market = st.selectbox("시장", ["전체", "KOSPI", "KOSDAQ"], key="scr_market")

    note = {"average": f"최근 {n_years}년 평균", "CAGR": f"최근 {n_years}년 CAGR",
            "YoY": "최신 연도 전년比"}[method]
    st.caption(f"연간(FY)·{state.STMT_LABELS_INV.get(state.get_stmt_type())} 기준 · "
               f"윈도우 집계 = **{note}** · 멀티플/시총은 최신 점값")

    n_passes = int(st.selectbox("퀀트 패스 수", [1, 2, 3], key="scr_npass"))
    passes = []
    for i in range(n_passes):
        with st.expander(f"패스 {i + 1}", expanded=(i == 0)):
            passes.append(_pass_controls(i, method))

    if st.button("스크리닝 실행", type="primary", width="stretch"):
        base = cache.screen_base_frame(n_years, method, state.get_stmt_type())
        if market != "전체":
            base = base[base["market"].str.upper() == market.upper()]
        final, counts = se.run_quant_passes(base, passes)
        st.session_state[_RESULT_META] = {
            "df": final.reset_index(drop=True),
            "method": method,
            "cols": _displayed_cols(passes),
            "counts": counts,
        }

    meta = st.session_state.get(_RESULT_META)
    if not meta:
        st.info("필터를 구성하고 **스크리닝 실행**을 누르세요. 결과 행을 클릭하면 우측에 시각화됩니다.")
        return

    df: pd.DataFrame = meta["df"]
    counts = meta["counts"]
    if len(counts) > 1:
        chain = " → ".join(f"P{i+1} {c}건" for i, c in enumerate(counts))
        st.markdown(f"**퀀트 축소**: {chain}")
    st.markdown(f"**결과 {len(df)}건**")

    if df.empty:
        st.warning("조건에 맞는 기업이 없습니다.")
        return

    disp = _build_display(df, meta["method"], meta["cols"])
    event = st.dataframe(disp, hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row",
                         key="screen_table")
    sel = event.selection.rows if event and event.selection else []
    if sel:
        state.set_focus_corp(df.iloc[sel[0]]["corp_code"])

    st.download_button("결과 CSV 내려받기", data=to_csv_bytes(df, index=False),
                       file_name="screen_results.csv", mime="text/csv")


def _build_display(df: pd.DataFrame, method: str, cols: list[str]) -> pd.DataFrame:
    recs = []
    for _, r in df.iterrows():
        rec = {
            "기업명": r["corp_name"],
            "종목코드": r.get("stock_code") or "—",
            "corp_code": r["corp_code"],
            "시장": r.get("market") or "—",
            "기간": int(r["n_periods"]) if pd.notna(r.get("n_periods")) else 0,
        }
        for mid in cols:
            rec[_label(mid)] = _fmt(mid, method, r.get(mid))
        recs.append(rec)
    return pd.DataFrame(recs)


# ── 우측: 선택기업 시각화(비파괴) ───────────────────────────────
def _right() -> None:
    if not state.get_focus_corp():
        st.info("← 결과 행을 선택하면 여기에 시각화가 표시됩니다.")
        return
    company_page.render()


def render() -> None:
    left, right = st.columns([5, 7], gap="large")
    with left:
        _left()
    with right:
        _right()
