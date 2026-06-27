"""
지표 해석기(resolver) — 선택 지표 × 기간 → tidy DataFrame.

기간별로 엔진 출력(compute_ratios)을 **한 번만** 계산하고, 각 MetricSpec 이 지정한
위치(컬럼 또는 ratios 속성)에서 값을 읽는다. 30개 지표를 골라도 기간당 1회 계산.

값은 원시값(금액=원, 비율=소수)으로 보존 — 표시 변환은 패널/units 가 담당.
"""
from __future__ import annotations

import pandas as pd

from analyzer.ratio_engine import compute_ratios
from app.registry.metrics import REGISTRY_BY_ID, MetricSpec


def _period_label(sf: dict, grain: str) -> str:
    if grain == "quarter":
        return f"{sf.get('calendar_year')} {sf.get('calendar_period')}"
    return str(sf.get("fiscal_year"))


def _read(spec: MetricSpec, sf: dict, ratios) -> object:
    if spec.source == "column":
        return sf.get(spec.key)
    # source == "ratios"
    return getattr(ratios, spec.key, None)


def build_metric_frame(series: list[dict], metric_ids: list[str], grain: str) -> pd.DataFrame:
    """
    tidy long DataFrame: period_label · period_end · metric_id · name · category ·
    unit · value(원시).

    series: std_v2(연간) 또는 calendar(분기) 행, 최신→과거. ratios 전기=직후(더 과거) 행.
    """
    specs = [REGISTRY_BY_ID[m] for m in metric_ids if m in REGISTRY_BY_ID]
    need_ratios = any(s.source == "ratios" for s in specs)
    rows = []
    n = len(series)
    for i, sf in enumerate(series):
        ratios = None
        if need_ratios:
            prev = series[i + 1] if i + 1 < n else None
            ratios = compute_ratios(sf, prev)
        label = _period_label(sf, grain)
        pe = sf.get("period_end")
        for spec in specs:
            rows.append({
                "period_label": label,
                "period_end": pe,
                "metric_id": spec.id,
                "name": spec.name_ko,
                "category": spec.category.value,
                "unit": spec.unit,
                "value": _read(spec, sf, ratios),
            })
    return pd.DataFrame(rows)
