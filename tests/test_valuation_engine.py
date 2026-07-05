"""
analyzer.valuation_engine.compute_multiples 회귀 테스트.

주가/시총 조회(get_market_data, DB)만 몽키패치로 고정값 주입하면 나머지 멀티플 산식은
순수. PER/PBR/PSR/PCR/EV·EBITDA/EBIT/FCF 골든값 + controlling_ni 우선을 고정(W4).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyzer.price_fetcher as _pf  # noqa: E402
from analyzer.valuation_engine import compute_multiples  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402

_FAKE_MARKET = {"market_cap": 20000, "close_price": 200, "shares_out": 100}

SF = {
    "controlling_ni": 144, "net_income": 999,   # 우선순위 검증: controlling_ni 채택
    "total_equity": 1200, "controlling_equity": 1200,
    "revenue": 1000, "cfo": 220, "ebitda": 260, "operating_income": 200,
    "fcf": 140, "net_debt": -100, "fiscal_year": 2024,
}


def _multiples(market=_FAKE_MARKET, sf=SF):
    orig = _pf.get_market_data
    _pf.get_market_data = lambda *a, **k: market
    try:
        return compute_multiples(sf, corp_code="X", stock_code="TEST",
                                 period_end=date(2024, 12, 31))
    finally:
        _pf.get_market_data = orig


def test_ev_and_price_multiples():
    mv = _multiples()
    assert mv.market_cap == 20000
    assert mv.ev == 20000 + (-100)            # 19900
    assert approx(mv.per, 20000 / 144)        # controlling_ni, not net_income
    assert approx(mv.pbr, 20000 / 1200)
    assert approx(mv.psr, 20000 / 1000)
    assert approx(mv.pcr, 20000 / 220)


def test_ev_multiples():
    mv = _multiples()
    assert approx(mv.ev_ebitda, 19900 / 260)
    assert approx(mv.ev_ebit, 19900 / 200)
    assert approx(mv.ev_fcf, 19900 / 140)


def test_negative_earnings_no_per():
    sf = dict(SF, controlling_ni=-50, net_income=-50)
    mv = _multiples(sf=sf)
    assert mv.per is None                     # ni<=0 → PER 없음
    assert mv.pbr is not None                 # 자본은 양수라 PBR 유지


def test_no_market_data_returns_empty():
    mv = _multiples(market=None)
    assert mv.market_cap is None and mv.per is None


def test_zero_market_cap_short_circuits():
    mv = _multiples(market={"market_cap": 0, "close_price": 0, "shares_out": 100})
    assert mv.per is None and mv.pbr is None


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
