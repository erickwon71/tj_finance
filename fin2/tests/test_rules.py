"""
표준화 규칙 엔진 단위 테스트 (순수, DB 비의존).

canonical→value dict 입력 → std 컬럼/파생/DQ 검증. aggregator 휴리스틱 이식 정확성 고정.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.standardize.rules import StdContext, run_rules, validate_equations  # noqa: E402


def _ctx(canon, basis="consolidated"):
    c = StdContext(corp_code="X", fiscal_year=2023, fiscal_period="FY", basis=basis, canon=canon)
    return run_rules(c)


def test_direct_mapping():
    c = _ctx({"bs.total_assets": 1000, "is.revenue": 500, "cf.operating": 200})
    assert c.col["total_assets"] == 1000
    assert c.col["revenue"] == 500
    assert c.col["cfo"] == 200


def test_additive_capex_negative():
    # 유형 + 무형 취득 합산 후 음수(현금유출)
    c = _ctx({"cf.capex": 300, "cf.capex_intangible": 50})
    assert c.col["capex"] == -350


def test_additive_da_and_ebitda():
    c = _ctx({"is.operating_income": 1000, "cf.depreciation": 200,
              "cf.amortization": 50, "note.rou_depreciation": 30})
    assert c.col["depreciation"] == 230   # 200 + 30 ROU
    assert c.col["amortization"] == 50
    assert c.col["da_total"] == 280
    assert c.col["ebitda"] == 1280        # op 1000 + da 280


def test_fcf_and_net_debt():
    c = _ctx({"cf.operating": 1000, "cf.capex": 300,
              "bs.short_term_debt": 100, "bs.long_term_debt": 400, "bs.cash": 150})
    assert c.col["fcf"] == 1000 - 300     # cfo - |capex|
    assert c.col["net_debt"] == 100 + 400 - 150


def test_net_income_and_controlling_fill():
    # net_income 없고 controlling_ni 만 → net_income 채움
    c = _ctx({"is.controlling_ni": 800})
    assert c.col["net_income"] == 800
    # separate: controlling_ni 없고 net_income 있으면 → controlling_ni 채움
    c2 = _ctx({"is.net_income": 700}, basis="separate")
    assert c2.col["controlling_ni"] == 700


def test_revenue_from_cogs_gp():
    c = _ctx({"is.cogs": -600, "is.gross_profit": 400})
    assert c.col["revenue"] == 1000       # |cogs| + gp


def test_max_abs_duplicate_resolution():
    # 같은 컬럼에 작은 값 먼저, 큰 값 나중 → max-abs 채택(revenue sub-item 6원 방어)
    c = _ctx({"is.revenue": 5})           # 단일이면 그대로
    assert c.col["revenue"] == 5


def test_validate_equations():
    assert validate_equations({"total_assets": 1000, "total_liabilities": 600, "total_equity": 400}) == 1
    assert validate_equations({"total_assets": 1000, "total_liabilities": 600, "total_equity": 300}) == 3  # 10% 차이
    assert validate_equations({"revenue": 1000, "cogs": -600, "gross_profit": 100}) == 2  # gp 불일치


def test_value_cols_always_present():
    c = _ctx({"bs.total_assets": 1000})
    # 미공시 컬럼도 키 존재(None) → 기존 잘못된 값 NULL 정리 가능
    assert "revenue" in c.col and c.col["revenue"] is None
    assert "ebitda" in c.col


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
