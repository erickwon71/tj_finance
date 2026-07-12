"""
확장 재무항목 tidy 프레임 변환 — resolver.build_metric_frame 과 동일 스키마를 반환해
차트빌더의 차트/표/CSV/프리셋 로직이 무변경으로 재사용되게 한다.

기존 series(annual_series/quarter_series)와 달리, 확장 항목은 corp+basis 단위로 이미 로드된
`rows`(app.data.extended.load_extended_all 결과)를 받아 순수 함수로 필터·변환만 한다 —
선택 지표가 바뀔 때마다 DB 를 다시 쳐야 하는 resolver 와 달리, rows 는 캐시(app.cache.
extended_series)에서 한 번만 로드하면 되기 때문.
"""
from __future__ import annotations

import pandas as pd

from app.registry.extended import EXTENDED_BY_ID
from app.registry.units import Category

_TIDY_COLS = ["period_label", "period_end", "metric_id", "name", "category", "unit", "value"]


def fetch_ext_frame(rows: list[dict], metric_ids: list[str], grain: str) -> pd.DataFrame:
    """
    rows: app.data.extended.load_extended_all() 결과(corp+basis 단위 전체 캐노니컬).
    metric_ids: EXTENDED_CATALOG id(canonical_account) 중 선택된 것.
    grain: "annual" 만 지원 — 그 외는 빈 프레임(분기 미지원, 호출부가 안내 캡션 표시).
    """
    empty = pd.DataFrame(columns=_TIDY_COLS)
    if grain != "annual" or not rows or not metric_ids:
        return empty

    specs = {mid: EXTENDED_BY_ID[mid] for mid in metric_ids if mid in EXTENDED_BY_ID}
    if not specs:
        return empty

    out = []
    for r in rows:
        spec = specs.get(r["canonical_account"])
        if spec is None:
            continue
        out.append({
            "period_label": str(r["fiscal_year"]),
            "period_end": r["period_end"],
            "metric_id": spec.id,
            "name": spec.name_ko,
            "category": Category.EXTENDED.value,
            "unit": spec.unit,
            "value": r["amount_won"],
        })
    return pd.DataFrame(out, columns=_TIDY_COLS) if out else empty
