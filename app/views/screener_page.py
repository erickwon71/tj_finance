"""
Screener 페이지 — Phase 4(윈도우 집계 + 퀀트 다단계 + 비파괴 분할 시각화).

좌(필터·결과) · 우(선택기업 시각화)로 분할(`st.columns([5,7])`). 좌측에서 윈도우
집계(average/CAGR/YoY, 최대 10년)와 ≤4개 퀀트 패스(filter→sort→limit)를 구성·실행하고,
결과 행을 클릭하면 우측에 PRD 05 `company_page` 패널을 재사용해 시각화한다(좌측 결과는 유지).

수치·집계·필터는 기존 엔진 재사용 → `run.py screen` / `analyze` 와 정합:
- `app.compute.screen_eval`(=ratio_engine `_cagr`/`_growth_rate`·screener `_check`)
- `app.cache.screen_base_frame`(윈도우 로드+집계 1회 캐시)
- `app.views.company_page`(우측 패널)
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from app import cache, state
from app.compute import screen_eval as se
from app.components.export import to_csv_bytes
from app.data import saved_screens as ss
from app.registry.metrics import METRIC_REGISTRY
from app.registry.units import UnitType
from app.views import company_page

# 저장/복원할 스크리너 위젯 세션 키(구성 스냅샷). scr_* = 상단 컨트롤, p{i}_* = 패스별.
_SCREEN_KEY_RE = re.compile(r"^(scr_|p\d+_)")
_JSONABLE = (str, int, float, bool, list, type(None))
# 저장 스냅샷에서 제외할 메타 위젯(저장바 자체 컨트롤 — 구성이 아님).
_SCREEN_KEY_EXCLUDE = {"scr_saved_pick", "scr_saved_name"}

# ── 필드 카탈로그(필터/정렬 가능) ──────────────────────────────
ALL_FIELD_IDS: list[str] = (
    se.WINDOW_METRIC_IDS + se.MULTIPLE_IDS + se.MASTER_IDS + [se.MARKET_CAP_ID]
)

_LABELS: dict[str, str] = {m.id: m.name_ko for m in METRIC_REGISTRY}
_LABELS.update(dict(se.MULTIPLE_FIELDS))
_LABELS.update(dict(se.MASTER_FIELDS))
_LABELS[se.MARKET_CAP_ID] = "시가총액(조)"

_RESULT_META = "screen_meta"   # session_state: {"df", "method", "cols", "counts"}


def _label(mid: str) -> str:
    return _LABELS.get(mid, mid)


def _windowable(mid: str) -> bool:
    """윈도우 집계 대상 여부(멀티플·시총은 최신 점값)."""
    return mid in se.WINDOW_METRIC_IDS


def _unit_suffix(mid: str, method: str) -> str:
    """필터 입력 단위 표기. 금액=(억원)·비율=(%)·배수=(배)·일수=(일)·시총=(조원)·랭크=(위).
    CAGR/YoY/QoQ 집계 시엔 금액도 성장률(%)이 되므로 effective_unit 로 판정."""
    if mid == se.MARKET_CAP_ID:
        return " (조원)"
    if mid == se.MAGIC_RANK_ID:
        return " (위)"
    unit = se.effective_unit(mid, method)
    return {UnitType.PCT: " (%)", UnitType.AMOUNT_EOK: " (억원)",
            UnitType.DAYS: " (일)", UnitType.MULTIPLE_X: " (배)"}.get(unit, "")


# ── 셀 포맷 ────────────────────────────────────────────────────
def _fmt(mid: str, method: str, value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if mid == se.MARKET_CAP_ID:
        return f"{value:.2f}조"
    if mid == se.MAGIC_RANK_ID:
        return f"{int(value)}위"
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

    # 지표별 구간 필터: 최소(이상)·최대(이하). 한쪽만 입력하면 단측 조건, 둘 다면 구간.
    filters: dict[str, list] = {}
    for mid in metrics:
        sfx = _unit_suffix(mid, method)
        c0, c1, c2 = st.columns([2, 1, 1])
        c0.markdown(f"**{_label(mid)}**{sfx}")
        vmin = c1.number_input("최소(이상)", value=None, step=1.0,
                               key=f"p{i}_min_{mid}", placeholder="하한 없음")
        vmax = c2.number_input("최대(이하)", value=None, step=1.0,
                               key=f"p{i}_max_{mid}", placeholder="상한 없음")
        conds = []
        if vmin is not None:
            conds.append(se.make_threshold(mid, method, ">=", float(vmin)))
        if vmax is not None:
            conds.append(se.make_threshold(mid, method, "<=", float(vmax)))
        if conds:
            filters[mid] = conds

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


# ── 저장된 스크린(구성 스냅샷) ─────────────────────────────────
def _capture_screen_config() -> dict:
    """현재 스크리너 위젯 구성(scr_*, p{i}_*)을 JSON 직렬화 가능 dict 로."""
    return {k: v for k, v in st.session_state.items()
            if _SCREEN_KEY_RE.match(k) and k not in _SCREEN_KEY_EXCLUDE
            and isinstance(v, _JSONABLE)}


def _apply_screen_config(cfg: dict) -> None:
    """저장된 구성을 세션에 되돌린다(호출 후 st.rerun 필요)."""
    for k, v in cfg.items():
        if _SCREEN_KEY_RE.match(k) and k not in _SCREEN_KEY_EXCLUDE:
            st.session_state[k] = v


def _saved_screen_bar() -> None:
    names = ss.list_screens()
    with st.expander("💾 저장된 스크린 (구성 저장·불러오기)", expanded=False):
        c1, c2, c3 = st.columns([3, 1, 1])
        picked = c1.selectbox("저장된 스크린", ["(선택)"] + names,
                              key="scr_saved_pick", label_visibility="collapsed")
        if c2.button("불러오기", width="stretch", disabled=(picked == "(선택)")):
            cfg = ss.get_screen(picked) or {}
            _apply_screen_config(cfg)
            st.rerun()
        if c3.button("삭제", width="stretch", disabled=(picked == "(선택)")):
            ss.delete_screen(picked)
            st.rerun()

        c4, c5 = st.columns([3, 1])
        new_name = c4.text_input("새 스크린 이름", key="scr_saved_name",
                                 placeholder="예: 고ROE·저PER 가치주",
                                 label_visibility="collapsed")
        if c5.button("저장", width="stretch", disabled=(not new_name.strip())):
            ss.save_screen(new_name.strip(), _capture_screen_config())
            st.success(f"스크린 '{new_name.strip()}' 저장됨")
            st.rerun()


# ── 좌측: 컨트롤 + 결과 ─────────────────────────────────────────
def _left() -> None:
    st.header("🔎 스크리너")
    _saved_screen_bar()
    method_label = {"average": "평균", "CAGR": "CAGR", "YoY": "YoY", "QoQ": "전분기比"}

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        grain_label = st.selectbox("기간 단위", ["연간", "분기"], key="scr_grain")
    grain = "quarter" if grain_label == "분기" else "annual"
    with c2:
        if grain == "quarter":
            n_periods = int(st.slider("집계 기간(분기)", 4, 20, 8, key="scr_nq"))
        else:
            n_periods = int(st.slider("집계 기간(년)", 1, 10, 3, key="scr_n"))
    with c3:
        # grain 별 옵션/키 분리 → 분기전용 QoQ 가 연간 옵션에 없어 생기는 충돌 방지
        if grain == "quarter":
            method = st.selectbox("집계 방법", se.AGG_METHODS_QUARTER,
                                  format_func=lambda m: method_label[m], key="scr_method_q")
        else:
            method = st.selectbox("집계 방법", se.AGG_METHODS,
                                  format_func=lambda m: method_label[m], key="scr_method_a")
    mc1, mc2 = st.columns([1, 1])
    with mc1:
        market = st.selectbox("시장", ["전체", "KOSPI", "KOSDAQ"], key="scr_market")
    with mc2:
        miss_label = st.selectbox(
            "결측값(NULL) 처리", ["제외", "통과"], key="scr_missing",
            help="필터 지표가 없는(NULL) 기업을 제외(기본)할지, 그 필터에 한해 통과시킬지. "
                 "'통과'는 EBITDA·R&D 등 커버리지 낮은 지표로 모집단이 과도히 잘릴 때 유용.")
    include_missing = miss_label == "통과"

    unit = "분기" if grain == "quarter" else "년"
    yoy_note = "최신 분기 전년동기比" if grain == "quarter" else "최신 연도 전년比"
    note = {"average": f"최근 {n_periods}{unit} 평균",
            "CAGR": f"최근 {n_periods}{unit} CAGR(연환산)", "YoY": yoy_note,
            "QoQ": "최신 분기 직전분기比"}[method]
    grain_txt = "분기(달력분기 이산)" if grain == "quarter" else "연간(FY)"
    pt_txt = "멀티플/대가는 TTM(직전 4분기)" if grain == "quarter" else "멀티플/시총은 최신 점값"
    st.caption(f"{grain_txt}·{state.STMT_LABELS_INV.get(state.get_stmt_type())} 기준 · "
               f"윈도우 집계 = **{note}** · {pt_txt}")

    n_passes = int(st.selectbox("퀀트 패스 수", [1, 2, 3, 4], key="scr_npass"))
    passes = []
    for i in range(n_passes):
        with st.expander(f"패스 {i + 1}", expanded=(i == 0)):
            passes.append(_pass_controls(i, method))

    if st.button("스크리닝 실행", type="primary", width="stretch"):
        base = cache.screen_base_frame(n_periods, method, state.get_stmt_type(), grain)
        if market != "전체":
            base = base[base["market"].str.upper() == market.upper()]
        final, counts = se.run_quant_passes(base, passes, include_missing=include_missing)
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

    csv_df = df.drop(columns=["_transitions"], errors="ignore")  # 내부 표시용 컬럼 제외
    st.download_button("결과 CSV 내려받기", data=to_csv_bytes(csv_df, index=False),
                       file_name="screen_results.csv", mime="text/csv")


def _build_display(df: pd.DataFrame, method: str, cols: list[str]) -> pd.DataFrame:
    recs = []
    for _, r in df.iterrows():
        rec = {
            "기업명": r["corp_name"],
            "종목코드": r.get("stock_code") or "—",
            "corp_code": r["corp_code"],
            "시장": r.get("market") or "—",
            "기준": {"consolidated": "연결", "separate": "별도"}.get(r.get("used_stmt"), "—"),
            "기간": int(r["n_periods"]) if pd.notna(r.get("n_periods")) else 0,
        }
        trans = r.get("_transitions") or {}
        for mid in cols:
            # 흑자↔적자 전환은 %가 오도 소지가 있어 라벨로 대체(값·정렬·필터는 원 수치 유지).
            rec[_label(mid)] = trans[mid] if mid in trans else _fmt(mid, method, r.get(mid))
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
