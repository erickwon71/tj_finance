"""PRD 03 §5.1 분기환산 단위 테스트 — flow 차감 / stock 스냅샷 / 결측 미생성.

실행: python -m fin2.tests.test_quarterly
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.standardize.quarterly import (  # noqa: E402
    _build_discrete, _FLOW_COLS, _STOCK_COLS, _QUARTER_SPEC,
)


def _row(fy, fp, **vals):
    base = {"corp_code": "00000000", "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": "consolidated", "period_end": None, "is_ifrs": True,
            "bs_rcept": "r", "is_rcept": "r", "cf_rcept": "r"}
    base.update(vals)
    return base


def test_flow_columns_are_is_cf():
    assert "revenue" in _FLOW_COLS and "net_income" in _FLOW_COLS and "cfo" in _FLOW_COLS
    assert "total_assets" not in _FLOW_COLS and "total_equity" not in _FLOW_COLS


def test_stock_columns_are_bs():
    assert "total_assets" in _STOCK_COLS and "net_debt" in _STOCK_COLS
    assert "revenue" not in _STOCK_COLS and "cfo" not in _STOCK_COLS


def test_q1_is_cumulative_copy():
    q1 = _build_discrete(_row(2024, "Q1", revenue=100, total_assets=1000), None, "Q1")
    assert q1["revenue"] == 100           # Q1 = Q1누적
    assert q1["total_assets"] == 1000     # stock 스냅샷
    assert q1["is_discrete"] is True and q1["applied_rules"] == ["quarterly_derived"]


def test_q2_is_difference():
    h1 = _row(2024, "H1", revenue=250, net_income=40, total_assets=1200)
    q1 = _row(2024, "Q1", revenue=100, net_income=15, total_assets=1000)
    q2 = _build_discrete(h1, q1, "Q2")
    assert q2["revenue"] == 150           # 250 − 100
    assert q2["net_income"] == 25         # 40 − 15
    assert q2["total_assets"] == 1200     # H1 분기말 스냅샷(차감 안 함)


def test_q4_difference():
    fy = _row(2024, "FY", revenue=1000, cfo=300, total_equity=500)
    q3 = _row(2024, "Q3", revenue=720, cfo=210, total_equity=480)
    q4 = _build_discrete(fy, q3, "Q4")
    assert q4["revenue"] == 280           # 1000 − 720
    assert q4["cfo"] == 90                # 300 − 210
    assert q4["total_equity"] == 500      # FY(12-31) 스냅샷


def test_missing_component_column_is_none_not_estimated():
    h1 = _row(2024, "H1", revenue=250, net_income=None)   # net_income 누락
    q1 = _row(2024, "Q1", revenue=100, net_income=15)
    q2 = _build_discrete(h1, q1, "Q2")
    assert q2["revenue"] == 150
    assert q2["net_income"] is None       # 한쪽 None → 추정 금지
    assert q2["data_quality"] == 1        # end 의 net_income 이 None 이라 dq 판정서 제외


def test_telescoping_sum_equals_fy():
    # Q1+Q2+Q3+Q4 = FY (구성상 항등). revenue 로 확인.
    q1 = _row(2024, "Q1", revenue=100); h1 = _row(2024, "H1", revenue=250)
    q3 = _row(2024, "Q3", revenue=720); fy = _row(2024, "FY", revenue=1000)
    d1 = _build_discrete(q1, None, "Q1")["revenue"]
    d2 = _build_discrete(h1, q1, "Q2")["revenue"]
    d3 = _build_discrete(q3, h1, "Q3")["revenue"]
    d4 = _build_discrete(fy, q3, "Q4")["revenue"]
    assert d1 + d2 + d3 + d4 == 1000
    assert d1 + d2 == 250                 # Q1+Q2 = H1


def test_no_flow_returns_none():
    # flow 전무(BS만) → 이산분기 미생성.
    bs_only = _row(2024, "Q1", total_assets=1000)
    assert _build_discrete(bs_only, None, "Q1") is None


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
