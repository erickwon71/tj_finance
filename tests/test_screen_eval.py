"""
app.compute.screen_eval 회귀 테스트 — 스크리너 집계·단위·임계·퀀트 패스 (W4).

윈도우 집계(average/YoY/CAGR/QoQ), 표시 단위(effective_unit), UI값→원시 임계
(make_threshold), 필터·정렬·한도(apply_pass), 마법공식 랭크(add_magic_rank)를 고정.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from app.compute import screen_eval as se  # noqa: E402
from app.registry.units import UnitType  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402


def test_aggregate_average():
    assert approx(se.aggregate([10, 20, None, 30], "average", 4, "annual"), 20.0)
    assert se.aggregate([], "average", 4) is None


def test_aggregate_yoy():
    assert approx(se.aggregate([110, 100], "YoY", 2, "annual"), 0.1)
    # 분기 YoY = 4분기 전 대비
    assert approx(se.aggregate([120, None, None, None, 100], "YoY", 5, "quarter"), 0.2)


def test_aggregate_qoq():
    assert approx(se.aggregate([120, 100], "QoQ", 2, "quarter"), 0.2)


def test_aggregate_cagr():
    # end=121, start=100, span=2yr → (121/100)^0.5 - 1 = 0.1
    assert approx(se.aggregate([121, None, 100], "CAGR", 3, "annual"), 0.1)
    # 부호 전환/음수 start → 정의 불가
    assert se.aggregate([100, -50], "CAGR", 2, "annual") is None


def test_effective_unit():
    assert se.effective_unit("per", "average") == UnitType.MULTIPLE_X
    assert se.effective_unit("roe", "average") == UnitType.PCT
    assert se.effective_unit("roe", "CAGR") == UnitType.PCT          # 성장률
    assert se.effective_unit("revenue", "average") == UnitType.AMOUNT_EOK
    assert se.effective_unit("revenue", "YoY") == UnitType.PCT       # 집계가 성장률
    assert se.effective_unit("earnings_yield", "average") == UnitType.PCT
    assert se.effective_unit("peg", "average") == UnitType.MULTIPLE_X


def test_make_threshold():
    assert se.make_threshold("roe", "average", ">=", 10) == ("gte", 0.1)
    assert se.make_threshold("revenue", "average", ">=", 100) == ("gte", 100 * se.EOK)
    assert se.make_threshold("per", "average", "<=", 15) == ("lte", 15)
    # CAGR 이면 금액 지표도 성장률(%) → 소수 변환
    assert se.make_threshold("revenue", "CAGR", ">", 5) == ("gt", 0.05)


def test_apply_pass_filter_sort_limit():
    df = pd.DataFrame([
        {"corp_code": "A", "roe": 0.15, "market_cap_jo": 5},
        {"corp_code": "B", "roe": 0.05, "market_cap_jo": 10},   # roe<0.1 탈락
        {"corp_code": "C", "roe": 0.20, "market_cap_jo": 3},
        {"corp_code": "D", "roe": 0.12, "market_cap_jo": 8},
    ])
    out = se.apply_pass(df, {"roe": ("gte", 0.1)}, "market_cap_jo", False, 2)
    # 통과 A/C/D → 시총 내림차순 D(8),A(5),C(3) → 상위 2 = D,A
    assert list(out["corp_code"]) == ["D", "A"]


def test_apply_pass_missing_policy():
    df = pd.DataFrame([
        {"corp_code": "A", "roe": 0.15},
        {"corp_code": "B", "roe": None},   # 결측
    ])
    excl = se.apply_pass(df, {"roe": ("gte", 0.1)}, None, False, None, include_missing=False)
    assert list(excl["corp_code"]) == ["A"]
    incl = se.apply_pass(df, {"roe": ("gte", 0.1)}, None, False, None, include_missing=True)
    assert set(incl["corp_code"]) == {"A", "B"}


def test_range_filter_and_counts():
    df = pd.DataFrame([{"corp_code": c, "roe": v} for c, v in
                       [("A", 0.05), ("B", 0.15), ("C", 0.25), ("D", 0.40)]])
    # 0.1 <= roe <= 0.30 → B, C
    out, counts = se.run_quant_passes(
        df, [{"filters": {"roe": [("gte", 0.1), ("lte", 0.30)]}, "sort_by": "roe",
              "asc": True, "limit": None}])
    assert list(out["corp_code"]) == ["B", "C"]
    assert counts == [2]


def test_magic_rank():
    df = pd.DataFrame([
        {"corp_code": "A", "earnings_yield": 0.12, "return_on_capital": 0.40},  # 최우수
        {"corp_code": "B", "earnings_yield": 0.10, "return_on_capital": 0.30},
        {"corp_code": "C", "earnings_yield": 0.05, "return_on_capital": 0.10},
    ])
    out = se.add_magic_rank(df)
    assert list(out[se.MAGIC_RANK_ID]) == [1.0, 2.0, 3.0]


def test_magic_rank_missing_is_na():
    df = pd.DataFrame([
        {"corp_code": "A", "earnings_yield": 0.12, "return_on_capital": 0.40},
        {"corp_code": "B", "earnings_yield": 0.10, "return_on_capital": None},
    ])
    out = se.add_magic_rank(df)
    assert out.loc[out["corp_code"] == "A", se.MAGIC_RANK_ID].iloc[0] == 1.0
    assert pd.isna(out.loc[out["corp_code"] == "B", se.MAGIC_RANK_ID].iloc[0])


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
