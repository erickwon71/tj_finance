"""
analyzer.ratio_engine.compute_ratios 회귀 테스트 (순수, DB 비의존).

깔끔한 정수 입력으로 손계산 가능한 골든값을 고정 — 공식이 조용히 바뀌면 실패한다(W4).
ROE/ROA 는 전기 평균자본·평균자산, ROIC 는 NOPAT/투하자본, 운전자본은 365일 기준.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.ratio_engine import _cagr, _growth_rate, compute_ratios  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402

CURR = {
    "revenue": 1000, "cogs": 600, "gross_profit": 400, "sga": 200,
    "operating_income": 200, "ebt": 180, "tax_expense": 36, "net_income": 144,
    "controlling_ni": 144, "ebitda": 260, "da_total": 60,
    "cfo": 220, "capex": -80, "fcf": 140,
    "total_assets": 2000, "current_assets": 800, "current_liabilities": 400,
    "total_liabilities": 800, "total_equity": 1200, "controlling_equity": 1200,
    "receivables": 100, "inventory": 150, "trade_payables": 120, "cash": 300,
    "net_debt": -100, "interest_expense": 20, "ppe": 900, "rd_expense": 50,
    "shares_out": 100,
}
PREV = {
    "revenue": 800, "operating_income": 160, "net_income": 120,
    "total_assets": 1800, "total_equity": 1000, "controlling_ni": 120,
    "controlling_equity": 1000, "gross_profit": 320,
}


def test_margins():
    r = compute_ratios(CURR, PREV)
    assert approx(r.gross_margin, 0.4)
    assert approx(r.op_margin, 0.2)
    assert approx(r.net_margin, 0.144)
    assert approx(r.ebitda_margin, 0.26)


def test_roe_roa_use_average_balances():
    r = compute_ratios(CURR, PREV)
    # avg_eq=(1200+1000)/2=1100, avg_ta=(2000+1800)/2=1900
    assert approx(r.roe, 144 / 1100)
    assert approx(r.roa, 144 / 1900)
    assert approx(r.asset_turnover, 1000 / 1900)


def test_roe_no_prev_uses_current_only():
    # 전기 없으면 _avg([eq]) = eq (평균 아님)
    r = compute_ratios(CURR, None)
    assert approx(r.roe, 144 / 1200)


def test_tax_and_roic():
    r = compute_ratios(CURR, PREV)
    assert approx(r.effective_tax_rate, 36 / 180)  # 0.2
    # nopat=int(200*(1-0.2))=160, invested=eq+net_debt=1200+(-100)=1100
    assert r.nopat == 160
    assert r.invested_capital == 1100
    assert approx(r.roic, 160 / 1100)


def test_stability():
    r = compute_ratios(CURR, PREV)
    assert approx(r.debt_ratio, 800 / 1200)
    assert approx(r.current_ratio, 2.0)
    assert approx(r.interest_coverage, 200 / 20)   # 10x, abs(int_ex)
    assert approx(r.net_debt_ebitda, -100 / 260)   # 음수여도 계산


def test_capex_fcf_quality():
    r = compute_ratios(CURR, PREV)
    assert approx(r.capex_to_revenue, 80 / 1000)   # abs(capex)
    assert approx(r.capex_to_dep, 80 / 60)
    assert r.fcf == 140
    assert approx(r.fcf_to_revenue, 0.14)
    assert approx(r.cfo_to_ni, 220 / 144)
    assert approx(r.accrual_ratio, (144 - 220) / 2000)


def test_working_capital_days():
    r = compute_ratios(CURR, PREV)
    assert approx(r.dso, 100 * 365 / 1000)   # 36.5
    assert approx(r.dio, 150 * 365 / 600)    # 91.25
    assert approx(r.dpo, 120 * 365 / 600)    # 73.0
    assert approx(r.ccc, 36.5 + 91.25 - 73.0)


def test_growth():
    r = compute_ratios(CURR, PREV)
    assert approx(r.revenue_growth, 0.25)
    assert approx(r.op_income_growth, 0.25)
    assert approx(r.net_income_growth, 0.2)
    assert approx(r.asset_growth, (2000 - 1800) / 1800)


def test_growth_rate_guards():
    assert _growth_rate(110, 100) == 0.1
    assert _growth_rate(50, 0) is None        # 전기 0 → None
    assert _growth_rate(None, 100) is None
    # ⚠ 현행 코드는 prev==0 만 가드 → 음수 전기는 None 이 아니라 (c-p)/|p| 반환.
    #    docstring("음수이면 None")과 불일치. 여기서는 실제 동작을 고정(회귀 감지용).
    assert _growth_rate(50, -10) == 6.0


def test_cagr():
    # (121/100)^(1/2) - 1 = 0.1
    assert approx(_cagr(100, 121, 2), 0.1)
    assert _cagr(0, 100, 2) is None           # start<=0 → None
    assert _cagr(100, 121, 0) is None         # years<=0 → None


def test_missing_denominators_return_none():
    r = compute_ratios({"revenue": 0, "operating_income": 100}, None)
    assert r.op_margin is None                # rev=0 → safe_div None
    assert r.roe is None                      # eq 없음


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
