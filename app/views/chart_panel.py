"""
차트 패널 (Plotly).

Phase 1: 주가 차트 — 종가 라인 + 거래량, log 스케일 토글, 장기간 주간 다운샘플.
Phase 2+: 지표 시계열 차트(금액/비율 이중축).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# 다운샘플 임계: 이 행수를 넘으면 주간(W) 리샘플로 응답성 유지
_DOWNSAMPLE_THRESHOLD = 1500


def _to_frame(price_rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(price_rows)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()
    return df


def _maybe_downsample(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if len(df) <= _DOWNSAMPLE_THRESHOLD:
        return df, False
    agg = {
        "open_price": "first", "high_price": "max", "low_price": "min",
        "close_price": "last", "volume": "sum", "market_cap": "last",
    }
    cols = {k: v for k, v in agg.items() if k in df.columns}
    weekly = df.resample("W").agg(cols).dropna(subset=["close_price"])
    return weekly, True


def render_price_chart(price_rows: list[dict], title: str = "주가",
                       log_scale: bool = False, candlestick: bool = False,
                       key: str | None = None) -> None:
    """주가 차트 렌더. close_price 라인(또는 캔들) + 거래량."""
    df = _to_frame(price_rows)
    if df.empty:
        st.info("주가 데이터가 없습니다.")
        return

    df, downsampled = _maybe_downsample(df)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.74, 0.26], vertical_spacing=0.03,
        subplot_titles=(title, "거래량"),
    )

    if candlestick and {"open_price", "high_price", "low_price"}.issubset(df.columns):
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["open_price"], high=df["high_price"],
            low=df["low_price"], close=df["close_price"], name="주가",
            increasing_line_color="#d32f2f", decreasing_line_color="#1976d2",
        ), row=1, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False)
    else:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["close_price"], name="종가",
            line=dict(color="#1f77b4", width=1.4), mode="lines",
        ), row=1, col=1)

    if "volume" in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df["volume"], name="거래량",
            marker_color="#b0bec5",
        ), row=2, col=1)

    fig.update_yaxes(
        type="log" if log_scale else "linear",
        title_text="원(log)" if log_scale else "원", row=1, col=1,
    )
    fig.update_yaxes(title_text="주", row=2, col=1)
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False, hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True, key=key)
    cap = f"{df.index.min().date()} ~ {df.index.max().date()}"
    if downsampled:
        cap += " · 주간 다운샘플(장기간)"
    st.caption(cap)


_EOK = 100_000_000


# 재무 항목 색상 팔레트 (최대 3개)
_FIN_COLORS = ["#d62728", "#2ca02c", "#ff7f0e"]
_FIN_BAR_FILL = "rgba(214,39,40,0.55)"

_METRIC_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
                  "#8c564b", "#17becf", "#e377c2"]


def render_metric_chart(frame, key: str | None = None) -> None:
    """
    지표 시계열 차트 — 금액(억원)은 좌축, 비율/배수/일수는 우축에 배치(이중축).
    frame: app.compute.resolver.build_metric_frame 산출(tidy).
    """
    from app.registry.units import AMOUNT_UNITS, UnitType, display_value

    if frame is None or frame.empty:
        st.info("표시할 지표를 선택하세요.")
        return

    has_amount = any(u in AMOUNT_UNITS for u in frame["unit"].unique())
    has_other = any(u not in AMOUNT_UNITS for u in frame["unit"].unique())
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    for i, (mid, g) in enumerate(frame.groupby("metric_id", sort=False)):
        g = g.sort_values("period_end")
        unit = g["unit"].iloc[0]
        name = g["name"].iloc[0]
        ys = [display_value(v, unit) for v in g["value"]]
        on_right = unit not in AMOUNT_UNITS
        suffix = {UnitType.AMOUNT_EOK: "억", UnitType.PCT: "%",
                  UnitType.MULTIPLE_X: "x", UnitType.DAYS: "일"}.get(unit, "")
        fig.add_trace(go.Scatter(
            x=g["period_end"], y=ys, name=f"{name}({unit.value})",
            mode="lines+markers",
            line=dict(color=_METRIC_COLORS[i % len(_METRIC_COLORS)], width=1.8),
            marker=dict(size=6),
            hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.2f}}{suffix}<extra></extra>",
        ), secondary_y=on_right)

    if has_amount:
        fig.update_yaxes(title_text="금액(억원)", secondary_y=False)
    if has_other:
        fig.update_yaxes(title_text="비율(%)/배수(x)/일수", secondary_y=True, showgrid=False)
    fig.update_layout(
        height=480, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


def render_price_financial_combined(
    price_rows: list[dict],
    fin_series: list[tuple],           # [(label, [(date, value_won), ...]), ...] 최대 3개
    grain: str = "annual",             # "annual" | "quarter" (막대 폭 결정)
    log_scale: bool = False,
    key: str | None = None,
) -> None:
    """
    주가(라인, 좌축 원) + 재무 항목 최대 3개(우축 억원)를 한 화면에 결합.
    재무 1개 = 막대, 2~3개 = 라인+마커(겹침 방지·비교 용이).
    """
    pdf = _to_frame(price_rows)
    if pdf.empty and not fin_series:
        st.info("표시할 데이터가 없습니다.")
        return
    pdf, downsampled = _maybe_downsample(pdf) if not pdf.empty else (pdf, False)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 주가 라인 (좌축)
    if not pdf.empty:
        fig.add_trace(go.Scatter(
            x=pdf.index, y=pdf["close_price"], name="주가",
            line=dict(color="#1f77b4", width=1.3), mode="lines",
        ), secondary_y=False)

    # 재무 항목 (우축, 억원)
    single = len(fin_series) == 1
    bar_days = 230 if grain == "annual" else 55
    for i, (label, pts) in enumerate(fin_series):
        if not pts:
            continue
        xs = [pe for pe, _ in pts]
        ys = [(v / _EOK) if v is not None else None for _, v in pts]
        if single:
            fig.add_trace(go.Bar(
                x=xs, y=ys, name=f"{label}(억원)", marker_color=_FIN_BAR_FILL,
                width=bar_days * 86_400_000,
                hovertemplate=f"{label}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.0f}}억<extra></extra>",
            ), secondary_y=True)
        else:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, name=f"{label}(억원)", mode="lines+markers",
                line=dict(color=_FIN_COLORS[i % 3], width=1.8),
                marker=dict(size=6),
                hovertemplate=f"{label}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.0f}}억<extra></extra>",
            ), secondary_y=True)

    right_title = f"{fin_series[0][0]}(억원)" if single and fin_series else "재무 (억원)"
    fig.update_yaxes(
        type="log" if log_scale else "linear",
        title_text="주가(원, log)" if log_scale else "주가(원)", secondary_y=False)
    fig.update_yaxes(title_text=right_title, secondary_y=True, showgrid=False)
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        hovermode="x unified", bargap=0.0,
    )
    st.plotly_chart(fig, use_container_width=True, key=key)
    if downsampled:
        st.caption("주가 주간 다운샘플(장기간)")
