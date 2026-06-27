"""
지표 패널 — 카테고리 그룹 멀티셀렉트 + 그래프/표 토글 (Phase 2).

레지스트리(METRIC_REGISTRY) 기반으로 임의 지표를 골라 시계열 표/그래프로 본다.
값은 resolver 가 원시값으로 산출하고, 단위별로 표시·축이 자동 결정된다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.compute.resolver import build_metric_frame
from app.components.export import download_button
from app.registry.metrics import metrics_by_category
from app.registry.units import format_value
from app.views.chart_panel import render_metric_chart

# 카테고리별 기본 선택 지표
_DEFAULT = {"revenue", "operating_income", "op_margin"}


def _ordered_periods(frame: pd.DataFrame) -> list[str]:
    """frame 등장 순서(최신→과거) 유지한 기간 라벨."""
    return list(dict.fromkeys(frame["period_label"]))


def _display_table(frame: pd.DataFrame) -> pd.DataFrame:
    """지표×기간 표시 문자열 표 (단위별 포맷)."""
    periods = _ordered_periods(frame)
    cells: dict[str, dict[str, str]] = {}
    units: dict[str, object] = {}
    for _, r in frame.iterrows():
        row_label = f"{r['name']} ({r['unit'].value})"
        cells.setdefault(row_label, {})[r["period_label"]] = format_value(r["value"], r["unit"])
        units[row_label] = r["unit"]
    df = pd.DataFrame(cells).T  # index=지표, columns=기간
    return df.reindex(columns=periods)


def _raw_table(frame: pd.DataFrame) -> pd.DataFrame:
    """CSV 용 원시값 표 (금액=원, 비율=소수). 단위 컬럼 포함."""
    periods = _ordered_periods(frame)
    cells: dict[str, dict[str, object]] = {}
    unit_col: dict[str, str] = {}
    for _, r in frame.iterrows():
        cells.setdefault(r["name"], {})[r["period_label"]] = r["value"]
        unit_col[r["name"]] = r["unit"].value
    df = pd.DataFrame(cells).T.reindex(columns=periods)
    df.insert(0, "단위", pd.Series(unit_col))
    return df


def render(series: list[dict], grain: str, corp_name: str = "", corp_code: str = "") -> None:
    if not series:
        st.info("재무 데이터가 없습니다.")
        return

    # 카테고리별 선택 메뉴 분리 (재무데이터 · 수익성 · 성장성 · 안정성)
    st.markdown("**지표 선택** — 카테고리별로 고르세요")
    by_cat = metrics_by_category()
    cols = st.columns(2)
    metric_ids: list[str] = []
    for i, (cat, specs) in enumerate(by_cat.items()):
        name_to_id = {s.name_ko: s.id for s in specs}
        default = [s.name_ko for s in specs if s.id in _DEFAULT]
        with cols[i % 2]:
            picked = st.multiselect(
                cat.value, list(name_to_id.keys()), default=default,
                key=f"metric_sel_{cat.name}")
        metric_ids += [name_to_id[n] for n in picked]

    if not metric_ids:
        st.info("표시할 지표를 1개 이상 선택하세요.")
        return

    view = st.radio("표시", ["표", "그래프"], horizontal=True, key="metric_view")

    frame = build_metric_frame(series, metric_ids, grain)
    grain_note = "분기 이산(3개월)" if grain == "quarter" else "연간 FY"

    # 표시도 카테고리별로 분리 (선택된 카테고리만, 레지스트리 순서)
    cat_order = [c.value for c in by_cat.keys()]
    present_cats = [cv for cv in cat_order if (frame["category"] == cv).any()]

    # 전체 기간(최신→과거) 라벨·기준일
    periods = (frame[["period_label", "period_end"]]
               .drop_duplicates().sort_values("period_end"))
    total = len(periods)

    st.divider()
    if view == "표":
        # 표 = 알고 있는 전체 기간 표시
        for cv in present_cats:
            sub = frame[frame["category"] == cv]
            st.markdown(f"#### {cv}")
            st.dataframe(_display_table(sub), width="stretch")
        st.caption(f"{grain_note} · 전체 {total}개 기간 · 금액=억원·비율=%·배수=x·일수=일")
        suffix = "quarter" if grain == "quarter" else "annual"
        download_button(
            _raw_table(frame), filename=f"{corp_name}_{corp_code}_metrics_{suffix}.csv",
            label="⬇ 지표 CSV (전체, 원시값: 금액=원·비율=소수)", key="metric_csv")
    else:
        # 그래프 = 기간축 확대/축소(최근 N개) 슬라이더
        unit_word = "분기" if grain == "quarter" else "연"
        if total > 4:
            n = st.slider(
                f"그래프 표시 기간 (최근 {unit_word} 수)", min_value=4, max_value=total,
                value=min(total, 20), key="metric_graph_n",
                help="오른쪽으로 갈수록 더 긴 기간(축소), 왼쪽일수록 최근만(확대)")
        else:
            n = total
        recent = set(periods.tail(n)["period_label"])
        fgraph = frame[frame["period_label"].isin(recent)]
        for cv in present_cats:
            sub = fgraph[fgraph["category"] == cv]
            st.markdown(f"#### {cv}")
            render_metric_chart(sub, key=f"metric_chart_{cv}")
        st.caption(f"{grain_note} · 최근 {n}/{total}개 기간 · 카테고리별 · "
                   f"금액(억원)=좌축 · 비율/배수/일수 (차트 드래그로 추가 확대 가능)")
