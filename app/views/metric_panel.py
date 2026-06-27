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

    if view == "표":
        st.dataframe(_display_table(frame), width="stretch")
        st.caption(f"{grain_note} · 금액=억원·비율=%·배수=x·일수=일")
        raw = _raw_table(frame)
        suffix = "quarter" if grain == "quarter" else "annual"
        download_button(
            raw, filename=f"{corp_name}_{corp_code}_metrics_{suffix}.csv",
            label="⬇ 지표 CSV (원시값: 금액=원·비율=소수)", key="metric_csv")
    else:
        render_metric_chart(frame, key="metric_chart")
        st.caption(f"{grain_note} · 금액(억원)=좌축 · 비율/배수/일수=우축")
