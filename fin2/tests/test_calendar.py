"""PRD 03 §5.3 Layer 2 달력정규화 단위 테스트 — CQ 매핑 / CY 합산·스냅샷 / 결측 미생성.

실행: python -m fin2.tests.test_calendar
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.standardize.calendar import (  # noqa: E402
    _MONTH_CQ, _cq_record, _cy_record, _CQ_ORDER,
)


def _disc(fy, fp, pe_month, pe_year, **vals):
    base = {"corp_code": "00000000", "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": "consolidated", "period_end": date(pe_year, pe_month, 28),
            "is_ifrs": True, "data_quality": 1,
            "revenue": None, "net_income": None, "cfo": None,
            "total_assets": None, "total_equity": None}
    base.update(vals)
    return base


def test_month_to_cq_mapping():
    assert _MONTH_CQ == {3: "CQ1", 6: "CQ2", 9: "CQ3", 12: "CQ4"}
    assert _MONTH_CQ.get(2) is None and _MONTH_CQ.get(11) is None  # 비정렬


def test_cq_record_carries_flow_and_stock():
    src = _disc(2024, "Q2", 6, 2024, revenue=150, net_income=25, total_assets=1200)
    rec = _cq_record("00000000", "consolidated", 2024, "CQ2", src, "native")
    assert rec["calendar_period"] == "CQ2" and rec["calendar_year"] == 2024
    assert rec["revenue"] == 150 and rec["total_assets"] == 1200
    assert rec["derivation"] == "native" and rec["is_complete"] is False
    assert rec["source_lineage"] == [[2024, "Q2"]]


def test_cy_flow_is_sum_stock_is_q4_snapshot():
    q = {
        "CQ1": _disc(2024, "Q1", 3, 2024, revenue=100, net_income=15, total_assets=1000),
        "CQ2": _disc(2024, "Q2", 6, 2024, revenue=150, net_income=25, total_assets=1200),
        "CQ3": _disc(2024, "Q3", 9, 2024, revenue=130, net_income=20, total_assets=1100),
        "CQ4": _disc(2024, "Q4", 12, 2024, revenue=280, net_income=40, total_assets=1300),
    }
    cy = _cy_record("00000000", "consolidated", 2024, q, "native")
    assert cy["calendar_period"] == "CY" and cy["is_complete"] is True
    assert cy["revenue"] == 660           # ΣCQ flow
    assert cy["net_income"] == 100
    assert cy["total_assets"] == 1300     # 12-31 스냅샷(CQ4, 합산 금지)
    assert cy["period_end"] == date(2024, 12, 31)
    assert len(cy["source_lineage"]) == 4


def test_cy_flow_none_if_any_quarter_missing_column():
    q = {
        "CQ1": _disc(2024, "Q1", 3, 2024, revenue=100, total_assets=1000),
        "CQ2": _disc(2024, "Q2", 6, 2024, revenue=150, total_assets=1200),
        "CQ3": _disc(2024, "Q3", 9, 2024, revenue=None, total_assets=1100),  # 결측
        "CQ4": _disc(2024, "Q4", 12, 2024, revenue=280, total_assets=1300),
    }
    cy = _cy_record("00000000", "consolidated", 2024, q, "native")
    assert cy["revenue"] is None          # 한 분기 None → 추정 금지
    assert cy["total_assets"] == 1300     # stock 은 스냅샷이라 영향 없음


def test_recomposed_derivation_for_nondec():
    src = _disc(2024, "Q4", 3, 2024, revenue=50)   # 3월결산사 fiscal Q4 → 달력 CQ1
    rec = _cq_record("00000000", "consolidated", 2024, "CQ1", src, "recomposed")
    assert rec["derivation"] == "recomposed"


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
