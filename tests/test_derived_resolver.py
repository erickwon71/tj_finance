"""
app.compute.resolver.build_metric_frame + app.compute.derived 회귀 테스트.

- resolver: column 지표는 원시값 그대로, ratios 지표는 compute_ratios(당기,전기) 산출.
- derived(D1): 비율(A÷B)·차분(A−B)·주당(A÷주식수) 값·단위·검증 규칙 고정.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from app.compute import derived as d  # noqa: E402
from app.compute.resolver import build_metric_frame  # noqa: E402
from app.registry.units import UnitType  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402

SERIES = [
    {"fiscal_year": 2024, "period_end": date(2024, 12, 31), "revenue": 1000,
     "cogs": 600, "operating_income": 200, "net_income": 144, "fcf": 140,
     "total_equity": 1200, "shares_out": 100},
    {"fiscal_year": 2023, "period_end": date(2023, 12, 31), "revenue": 800,
     "cogs": 500, "operating_income": 160, "net_income": 120, "fcf": 100,
     "total_equity": 1000, "shares_out": 100},
]


def _cell(frame, period_label, metric_id):
    m = frame[(frame["period_label"] == period_label) & (frame["metric_id"] == metric_id)]
    return m.iloc[0] if len(m) else None


def test_resolver_column_raw_value():
    f = build_metric_frame(SERIES, ["revenue"], "annual")
    c = _cell(f, "2024", "revenue")
    assert c["value"] == 1000                 # 원시값 그대로(원)
    assert c["unit"] == UnitType.AMOUNT_EOK


def test_resolver_ratio_uses_prev():
    f = build_metric_frame(SERIES, ["op_margin", "revenue_growth"], "annual")
    assert approx(_cell(f, "2024", "op_margin")["value"], 0.2)      # 200/1000
    assert approx(_cell(f, "2024", "revenue_growth")["value"], 0.25)  # (1000-800)/800
    assert _cell(f, "2024", "op_margin")["unit"] == UnitType.PCT
    # 가장 과거 기간은 전기 없음 → 성장률 결측(pandas NaN)
    assert pd.isna(_cell(f, "2023", "revenue_growth")["value"])


def test_derived_ratio():
    f = d.build_derived_frame(SERIES, [{"op": "ratio", "a": "fcf", "b": "operating_income"}], "annual")
    assert approx(_cell(f, "2024", "d_ratio_fcf_operating_income")["value"], 140 / 200)
    assert approx(_cell(f, "2023", "d_ratio_fcf_operating_income")["value"], 100 / 160)
    assert _cell(f, "2024", "d_ratio_fcf_operating_income")["unit"] == UnitType.MULTIPLE_X


def test_derived_diff():
    f = d.build_derived_frame(SERIES, [{"op": "diff", "a": "revenue", "b": "cogs"}], "annual")
    assert _cell(f, "2024", "d_diff_revenue_cogs")["value"] == 400
    assert _cell(f, "2024", "d_diff_revenue_cogs")["unit"] == UnitType.AMOUNT_EOK


def test_derived_pershare():
    f = d.build_derived_frame(SERIES, [{"op": "pershare", "a": "net_income"}], "annual")
    assert approx(_cell(f, "2024", "d_ps_net_income")["value"], 144 / 100)
    assert _cell(f, "2024", "d_ps_net_income")["unit"] == UnitType.WON_PER_SHARE


def test_derived_ratio_zero_denominator_none():
    series = [dict(SERIES[0], operating_income=0)]
    f = d.build_derived_frame(series, [{"op": "ratio", "a": "fcf", "b": "operating_income"}], "annual")
    assert _cell(f, "2024", "d_ratio_fcf_operating_income")["value"] is None


def test_validate_rules():
    assert d.validate({"op": "ratio", "a": "fcf", "b": "operating_income"}) is None
    assert d.validate({"op": "ratio", "a": "revenue", "b": "revenue"}) is not None   # 동일
    assert d.validate({"op": "diff", "a": "roe", "b": "roa"}) is not None            # 비금액 차분
    assert d.validate({"op": "pershare", "a": "op_margin"}) is not None              # 비금액 주당
    assert d.validate({"op": "pershare", "a": "net_income"}) is None
    assert d.validate({"op": "bogus", "a": "revenue"}) is not None                   # 잘못된 연산


def test_derived_names_and_units():
    assert d.derived_unit({"op": "ratio", "a": "fcf", "b": "net_income"}) == UnitType.MULTIPLE_X
    assert d.derived_unit({"op": "diff", "a": "revenue", "b": "cogs"}) == UnitType.AMOUNT_EOK
    assert d.derived_unit({"op": "pershare", "a": "fcf"}) == UnitType.WON_PER_SHARE
    assert d.derived_id({"op": "pershare", "a": "fcf"}) == "d_ps_fcf"


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
