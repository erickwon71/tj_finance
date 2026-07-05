"""
app.compute.master_metrics.compute_master 회귀 테스트 (Graham·Greenblatt·Lynch·Fisher, W4).

순수(sf_list + 시총 + 가격). Graham Number=√(22.5·EPS·BPS), EY=EBIT/EV,
ROC=EBIT/(순운전자본+순고정자산), PEG=PER/(순이익성장%×100) 등 산식을 고정한다.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compute.master_metrics import compute_master  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402

CURR = {
    "controlling_ni": 144, "net_income": 144, "total_equity": 1200,
    "controlling_equity": 1200, "shares_out": 100, "current_assets": 800,
    "total_liabilities": 800, "current_liabilities": 400, "ppe": 900,
    "operating_income": 200, "net_debt": -100, "revenue": 1000,
    "rd_expense": 50, "gross_profit": 400,
}
PREV = {"controlling_ni": 120, "net_income": 120, "revenue": 800, "gross_profit": 320}
MARKET_CAP = 20000
PRICE = 200


def _m():
    return compute_master([CURR, PREV], MARKET_CAP, PRICE)


def test_graham():
    m = _m()
    assert approx(m.eps, 1.44)
    assert approx(m.bps, 12.0)
    assert approx(m.graham_number, math.sqrt(22.5 * 1.44 * 12.0))
    assert approx(m.graham_upside, math.sqrt(22.5 * 1.44 * 12.0) / 200 - 1)
    assert approx(m.per_pbr, (20000 / 144) * (20000 / 1200))
    assert m.eps_positive_years == 2


def test_ncav():
    m = _m()
    # (유동자산 800 - 총부채 800)/100 = 0
    assert approx(m.ncav_per_share, 0.0)
    assert approx(m.ncav_to_price, 0.0)


def test_greenblatt():
    m = _m()
    # EY = EBIT/EV = 200/(20000-100)
    assert approx(m.earnings_yield, 200 / 19900)
    # ROC = 200 / ((800-400)+900) = 200/1300
    assert approx(m.return_on_capital, 200 / 1300)


def test_lynch_peg():
    m = _m()
    # PER=20000/144, growth=(144-120)/120=0.2 → PEG=PER/(0.2*100)
    assert approx(m.peg, (20000 / 144) / (0.2 * 100))


def test_fisher():
    m = _m()
    assert approx(m.rd_to_revenue, 0.05)
    # 매출총이익률 변화 = 400/1000 - 320/800 = 0
    assert approx(m.gross_margin_delta, 0.0)


def test_negative_growth_no_peg():
    prev = dict(PREV, controlling_ni=200, net_income=200)  # 이익 감소 → 성장률<0
    m = compute_master([CURR, prev], MARKET_CAP, PRICE)
    assert m.peg is None


def test_empty_returns_blank():
    m = compute_master([], MARKET_CAP, PRICE)
    assert m.eps is None and m.graham_number is None


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
