"""
자유조합 차트 (D1) — 임의의 재무/비율 지표를 골라 조합·시각화하는 빌더 페이지.

기존 지표 탭(metric_panel)이 "레지스트리 지표 다중선택 + 표/그래프"까지라면, 이 페이지는
그 위에 로드맵 D1 의 4가지를 더한다:
  ① 파생 필드(조합)  — 두 필드의 비율(A÷B)·차분(A−B), 임의 항목의 주당(A÷주식수)
  ② 주가/시총 오버레이 — 고른 금액 지표를 주가 라인 위에 결합
  ③ 프리셋 저장/로드  — 선택 구성을 로컬 JSON 으로 저장·복원
  ④ 연간/분기         — 좌측 사이드바 grain 을 그대로 따름

베이스·파생 모두 tidy 프레임(resolver/derived)으로 통일돼 차트(render_metric_chart)·
표·CSV(download_button)는 기존 컴포넌트를 재사용한다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import cache, state
from app.components.export import download_button
from app.compute import derived as _d
from app.compute.resolver import build_metric_frame
from app.compute.sources import fetch_dividend_frame, fetch_ext_frame
from app.data import presets as _presets
from app.registry.dividend import DIVIDEND_BY_ID, DIVIDEND_CATALOG
from app.registry.extended import EXTENDED_BY_ID, EXTENDED_CATALOG
from app.registry.metrics import METRIC_REGISTRY, REGISTRY_BY_ID
from app.registry.units import AMOUNT_UNITS, Category, UnitType, format_value
from app.views.chart_panel import render_metric_chart, render_price_financial_combined

# 파생 필드(비율·차분·주당) A/B 는 레지스트리 46종만 대상(app.compute.derived 가 REGISTRY_BY_ID
# 전용) — 확장 재무항목의 파생연산은 후속(Phase 5).
_ALL_IDS = [m.id for m in METRIC_REGISTRY]
_AMOUNT_IDS = [m.id for m in METRIC_REGISTRY if m.unit in AMOUNT_UNITS]

# "📈 기본 지표 선택" 은 레지스트리 + 확장 재무항목(EXTENDED_CATALOG) + 배당(DIVIDEND_CATALOG,
# Phase 2) 통합 풀.
_ALL_BASE_IDS = _ALL_IDS + [s.id for s in EXTENDED_CATALOG] + [s.id for s in DIVIDEND_CATALOG]
_EOK = 100_000_000


def _fmt_id(mid: str) -> str:
    """레지스트리 id → '이름 · 카테고리' 라벨."""
    s = REGISTRY_BY_ID[mid]
    return f"{s.name_ko} · {s.category.value}"


def _base_category(mid: str) -> str:
    """기본 지표 풀(레지스트리+확장) id → 카테고리 값."""
    if mid in REGISTRY_BY_ID:
        return REGISTRY_BY_ID[mid].category.value
    return Category.EXTENDED.value


def _fmt_base_id(mid: str) -> str:
    """기본 지표 풀 id → '이름 · 카테고리' 라벨(레지스트리+확장+배당 공통)."""
    if mid in REGISTRY_BY_ID:
        return _fmt_id(mid)
    s = EXTENDED_BY_ID.get(mid) or DIVIDEND_BY_ID[mid]
    return f"{s.name_ko} · {Category.EXTENDED.value}"


# ── 프리셋 바 ────────────────────────────────────────────
def _preset_bar() -> None:
    names = _presets.list_presets()
    with st.expander("💾 프리셋 (구성 저장·불러오기)", expanded=False):
        c1, c2 = st.columns([3, 1])
        picked = c1.selectbox("저장된 프리셋", ["(선택)"] + names,
                              key="cb_preset_pick", label_visibility="collapsed")
        if c2.button("불러오기", width="stretch", disabled=(picked == "(선택)")):
            payload = _presets.get_preset(picked) or {}
            st.session_state["cb_base"] = [i for i in payload.get("base_ids", [])
                                           if i in REGISTRY_BY_ID]
            st.session_state["cb_derived"] = [s for s in payload.get("derived", [])
                                              if _d.validate(s) is None]
            st.session_state["cb_overlay"] = bool(payload.get("overlay_price", False))
            st.session_state["cb_overlay_ids"] = [i for i in payload.get("overlay_ids", [])
                                                  if i in _AMOUNT_IDS]
            st.rerun()

        c3, c4 = st.columns([3, 1])
        new_name = c3.text_input("새 프리셋 이름", key="cb_preset_name",
                                 placeholder="예: 마진·현금흐름 세트",
                                 label_visibility="collapsed")
        if c4.button("저장", width="stretch", disabled=(not new_name.strip())):
            _presets.save_preset(new_name.strip(), {
                "base_ids": st.session_state.get("cb_base", []),
                "derived": st.session_state.get("cb_derived", []),
                "overlay_price": st.session_state.get("cb_overlay", False),
                "overlay_ids": st.session_state.get("cb_overlay_ids", []),
            })
            st.success(f"프리셋 '{new_name.strip()}' 저장됨")
            st.rerun()

        if names and picked != "(선택)":
            if st.button(f"🗑 '{picked}' 삭제", key="cb_preset_del"):
                _presets.delete_preset(picked)
                st.rerun()


# ── 파생 필드 빌더 ───────────────────────────────────────
def _derived_builder() -> None:
    st.session_state.setdefault("cb_derived", [])
    specs: list[dict] = st.session_state["cb_derived"]

    with st.expander(f"🧬 파생 필드 조합 ({len(specs)}개) — 비율·차분·주당", expanded=bool(specs)):
        c1, c2, c3, c4 = st.columns([2, 3, 3, 1.4])
        op = c1.selectbox("연산", list(_d.OP_LABELS), key="cb_op",
                          format_func=lambda o: _d.OP_LABELS[o])
        a = c2.selectbox("A 필드", _ALL_IDS, key="cb_a", format_func=_fmt_id)
        b_disabled = (op == "pershare")
        b = c3.selectbox("B 필드", _ALL_IDS, key="cb_b", format_func=_fmt_id,
                         disabled=b_disabled,
                         help="주당(A÷주식수)은 B를 사용하지 않습니다.")
        c4.markdown("<div style='height:1.9em'></div>", unsafe_allow_html=True)
        if c4.button("➕ 추가", width="stretch"):
            spec = {"op": op, "a": a, "b": (None if b_disabled else b)}
            err = _d.validate(spec)
            if err:
                st.error(err)
            elif any(_d.derived_id(s) == _d.derived_id(spec) for s in specs):
                st.warning("이미 추가된 파생 필드입니다.")
            else:
                specs.append(spec)
                st.rerun()

        if specs:
            st.caption("추가된 파생 필드")
            for i, s in enumerate(specs):
                lc, rc = st.columns([8, 1])
                lc.markdown(f"- **{_d.derived_name(s)}**  "
                            f"`{_d.derived_unit(s).value}`")
                if rc.button("❌", key=f"cb_del_{i}"):
                    specs.pop(i)
                    st.rerun()
        st.caption("비율=무차원(x) · 차분=금액(억원, 금액필드끼리) · 주당=원/주(금액필드).")


# ── 표 / CSV ─────────────────────────────────────────────
def _ordered_periods(frame: pd.DataFrame) -> list[str]:
    return (frame[["period_label", "period_end"]]
            .drop_duplicates().sort_values("period_end")["period_label"].tolist())


def _display_table(frame: pd.DataFrame) -> pd.DataFrame:
    periods = _ordered_periods(frame)
    cells: dict[str, dict[str, str]] = {}
    for _, r in frame.iterrows():
        row = f"{r['name']} ({r['unit'].value})"
        cells.setdefault(row, {})[r["period_label"]] = format_value(r["value"], r["unit"])
    return pd.DataFrame(cells).T.reindex(columns=periods)


def _raw_table(frame: pd.DataFrame) -> pd.DataFrame:
    periods = _ordered_periods(frame)
    cells: dict[str, dict[str, object]] = {}
    unit_col: dict[str, str] = {}
    for _, r in frame.iterrows():
        cells.setdefault(r["name"], {})[r["period_label"]] = r["value"]
        unit_col[r["name"]] = r["unit"].value
    df = pd.DataFrame(cells).T.reindex(columns=periods)
    df.insert(0, "단위", pd.Series(unit_col))
    return df


# ── 주가 오버레이 ────────────────────────────────────────
def _overlay_section(frame: pd.DataFrame, meta: dict, grain: str) -> None:
    st.session_state.setdefault("cb_overlay", False)
    on = st.toggle("주가 위에 금액 지표 결합(오버레이)", key="cb_overlay")
    if not on:
        return

    stock_code = meta.get("stock_code")
    lo, hi = cache.price_bounds(stock_code) if stock_code else (None, None)
    if not stock_code or not hi:
        st.info("주가 데이터가 없어 결합 차트를 표시할 수 없습니다.")
        return

    # 오버레이 후보 = 현재 프레임의 금액(억원) 시리즈(베이스+차분). 최대 3개.
    amount_rows = frame[frame["unit"] == UnitType.AMOUNT_EOK]
    options = amount_rows["metric_id"].drop_duplicates().tolist()
    if not options:
        st.caption("금액(억원) 지표를 1개 이상 선택하면 주가와 결합할 수 있습니다.")
        return
    id_to_name = dict(zip(amount_rows["metric_id"], amount_rows["name"]))

    # 세션값 정리(사라진 후보 제거) — 위젯 생성 전에 옵션과 정합.
    prev = [i for i in st.session_state.get("cb_overlay_ids", []) if i in options]
    st.session_state["cb_overlay_ids"] = prev or options[:1]

    c1, c2 = st.columns([3, 1])
    sel = c1.multiselect("결합할 금액 지표 (최대 3개)", options,
                         format_func=lambda i: id_to_name.get(i, i),
                         max_selections=3, key="cb_overlay_ids")
    log = c2.toggle("로그(주가)", value=True, key="cb_overlay_log")
    if not sel:
        return

    fin_series = []
    for mid in sel:
        g = amount_rows[amount_rows["metric_id"] == mid].sort_values("period_end")
        pts = [(pe, v) for pe, v in zip(g["period_end"], g["value"])
               if pe is not None and v is not None]
        if pts:
            fin_series.append((id_to_name.get(mid, mid), pts))
    if not fin_series:
        st.info("선택한 지표의 기간 데이터가 없습니다.")
        return

    start = min(pts[0][0] for _, pts in fin_series)
    prows = cache.price_series(stock_code, start, hi)
    render_price_financial_combined(prows, fin_series, grain=grain, log_scale=log,
                                    key="cb_combo")
    grain_note = "분기 이산(3개월)" if grain == "quarter" else "연간 FY"
    style = "막대" if len(fin_series) == 1 else "라인"
    st.caption(f"좌축=주가(원{', log' if log else ''}) · 우축=지표(억원, {style}) · "
               f"{grain_note} · 기간 전환은 좌측 사이드바")


# ── 페이지 ───────────────────────────────────────────────
def render() -> None:
    st.header("🧪 자유조합 차트")
    st.caption("원하는 재무·비율 지표를 골라 조합하고, 파생 필드(비율·차분·주당)와 주가 "
               "오버레이까지 자유롭게 구성합니다. 구성은 프리셋으로 저장·복원할 수 있습니다.")

    corp_code = state.get_focus_corp()
    if not corp_code:
        st.info("좌측 사이드바에서 기업을 검색·선택하세요.")
        return
    meta = cache.resolve_corp(corp_code)
    if not meta:
        st.warning(f"기업을 찾을 수 없습니다: {corp_code}")
        return

    from app.format import fmt_corp_identity
    st.subheader(fmt_corp_identity(meta["corp_name"], meta["corp_code"],
                                   meta.get("stock_code"), meta.get("market")))

    requested_stmt = state.get_stmt_type()
    grain = state.get_grain()
    if grain == "quarter":
        series, used_stmt = cache.quarter_series(corp_code, requested_stmt, quarters=400)
    else:
        series, used_stmt = cache.annual_series(corp_code, requested_stmt, years=200)
    if not series:
        st.warning(f"{'분기' if grain=='quarter' else '연간'} 표준화 재무제표 데이터가 없습니다.")
        return
    if used_stmt != requested_stmt:
        st.caption(f"※ {'연결' if requested_stmt=='consolidated' else '별도'} 데이터 없음 "
                   f"→ {'연결' if used_stmt=='consolidated' else '별도'} 표시")

    _preset_bar()

    # ① 기본 지표 선택 (카테고리 필터 + 레지스트리+확장 통합 다중선택)
    st.session_state.setdefault("cb_base", ["revenue", "operating_income", "op_margin"])
    cat_options = ["전체"] + [c.value for c in Category]
    cat_filter = st.selectbox("카테고리 필터", cat_options, key="cb_cat_filter")
    if cat_filter == "전체":
        options = _ALL_BASE_IDS
    else:
        options = [i for i in _ALL_BASE_IDS if _base_category(i) == cat_filter]
    # 위젯 안전: 필터로 가려져도 이미 선택된 항목은 옵션에 항상 포함(카테고리 전환 시 선택 유지).
    current = st.session_state.get("cb_base", [])
    options = list(dict.fromkeys(options + [i for i in current if i in _ALL_BASE_IDS]))
    base_ids = st.multiselect("📈 기본 지표 선택", options, format_func=_fmt_base_id,
                              key="cb_base")

    # ② 파생 필드 빌더
    _derived_builder()

    # 프레임 조립(베이스 + 확장 + 배당 + 파생)
    registry_ids = [i for i in base_ids if i in REGISTRY_BY_ID]
    extended_ids = [i for i in base_ids if i in EXTENDED_BY_ID]
    dividend_ids = [i for i in base_ids if i in DIVIDEND_BY_ID]

    frames = []
    if registry_ids:
        frames.append(build_metric_frame(series, registry_ids, grain))
    if extended_ids or dividend_ids:
        if grain != "annual":
            st.caption("※ 확장 재무항목/배당 지표는 연간(FY)만 지원합니다 — "
                       "좌측 사이드바에서 연간으로 전환하면 표시됩니다.")
        else:
            if extended_ids:
                ext_rows = cache.extended_series(corp_code, used_stmt)
                ext_frame = fetch_ext_frame(ext_rows, extended_ids, grain)
                if not ext_frame.empty:
                    frames.append(ext_frame)
            if dividend_ids:
                div_rows = cache.dividend_series_for_chart(corp_code, used_stmt)
                div_frame = fetch_dividend_frame(div_rows, dividend_ids, grain)
                if not div_frame.empty:
                    frames.append(div_frame)
    dframe = _d.build_derived_frame(series, st.session_state.get("cb_derived", []), grain)
    if not dframe.empty:
        frames.append(dframe)
    frames = [f for f in frames if not f.empty]
    if not frames:
        st.info("기본 지표를 1개 이상 선택하거나 파생 필드를 추가하세요.")
        return
    frame = pd.concat(frames, ignore_index=True)

    st.divider()
    view = st.radio("표시", ["그래프", "표"], horizontal=True, key="cb_view")
    grain_note = "분기 이산(3개월)" if grain == "quarter" else "연간 FY"

    periods = (frame[["period_label", "period_end"]]
               .drop_duplicates().sort_values("period_end"))
    total = len(periods)

    if view == "표":
        st.dataframe(_display_table(frame), width="stretch")
        st.caption(f"{grain_note} · 전체 {total}개 기간 · 금액=억원·비율=%/x·일수=일·주당=원/주")
        suffix = "quarter" if grain == "quarter" else "annual"
        download_button(_raw_table(frame),
                        filename=f"{meta['corp_name']}_{corp_code}_custom_{suffix}.csv",
                        label="⬇ CSV (전체, 원시값)", key="cb_csv")
    else:
        unit_word = "분기" if grain == "quarter" else "연"
        if total > 4:
            n = st.slider(f"그래프 표시 기간 (최근 {unit_word} 수)", min_value=4,
                          max_value=total, value=min(total, 20), key="cb_graph_n")
        else:
            n = total
        recent = set(periods.tail(n)["period_label"])
        render_metric_chart(frame[frame["period_label"].isin(recent)], key="cb_chart")
        st.caption(f"{grain_note} · 최근 {n}/{total}개 기간 · 금액(억원)=좌축 · "
                   f"비율/배수/일수/주당=우축 (차트 드래그로 추가 확대)")

    # ③ 주가 오버레이
    st.divider()
    st.markdown("#### 📉 주가 결합 (오버레이)")
    _overlay_section(frame, meta, grain)
