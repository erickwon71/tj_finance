"""
대가(Master) 지표 — Graham · Greenblatt · Lynch · Fisher.

Buffett·Piotroski 는 `analyzer.buffett_engine.compute_buffett` 에 기구현이므로 재사용하고,
여기서는 가격·주식수에 의존하는 가치투자 대가들의 커스텀 지표를 최신 FY 점값으로 계산한다.

값은 원시값 보존(금액=원, 비율=소수, 배수=x). 표시 변환은 뷰에서.
Greenblatt 마법공식의 **종합 랭크**는 단일 기업이 아니라 모집단 횡단면 순위라
`app.compute.screen_eval.add_magic_rank` 에서 base frame 에 부여한다.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Optional


@dataclass
class MasterMetrics:
    # ── Graham ──
    eps:               Optional[float] = None  # 주당순이익(원)
    bps:               Optional[float] = None  # 주당순자산(원)
    graham_number:     Optional[float] = None  # √(22.5·EPS·BPS) (원)
    graham_upside:     Optional[float] = None  # graham_number/price - 1
    ncav_per_share:    Optional[float] = None  # (유동자산-총부채)/주식수 (원)
    ncav_to_price:     Optional[float] = None  # NCAV주당/주가 (>1 = 청산가치 이하)
    per_pbr:           Optional[float] = None  # PER×PBR (Graham ≤22.5)
    eps_positive_years: Optional[int]  = None  # EPS>0 연속/구간 연수
    # ── Greenblatt 마법공식 ──
    earnings_yield:    Optional[float] = None  # EBIT/EV
    return_on_capital: Optional[float] = None  # EBIT/(순운전자본+순고정자산)
    # ── Lynch ──
    peg:               Optional[float] = None  # PER / (순이익성장%×100)
    # ── Fisher ──
    rd_to_revenue:     Optional[float] = None  # R&D/매출
    gross_margin_delta: Optional[float] = None  # 매출총이익률 전년 대비 변화(pp, 소수)


def _g(row: dict, key: str):
    return row.get(key) if row else None


def compute_master(
    sf_list: list[dict],
    market_cap: Optional[float],
    price: Optional[float],
) -> MasterMetrics:
    """
    sf_list: 최신→과거 FY 행. market_cap·price 는 최신 시장값.
    """
    m = MasterMetrics()
    if not sf_list:
        return m
    curr = sf_list[0]
    prev = sf_list[1] if len(sf_list) > 1 else None

    shares = _g(curr, "shares_out")
    ni     = _g(curr, "controlling_ni") or _g(curr, "net_income")
    eq     = _g(curr, "controlling_equity") or _g(curr, "total_equity")

    # ── Graham ──
    if ni and shares:
        m.eps = ni / shares
    if eq and shares:
        m.bps = eq / shares
    if m.eps and m.bps and m.eps > 0 and m.bps > 0:
        m.graham_number = math.sqrt(22.5 * m.eps * m.bps)
        if price and price > 0:
            m.graham_upside = m.graham_number / price - 1

    ca = _g(curr, "current_assets")
    tl = _g(curr, "total_liabilities")
    if ca is not None and tl is not None and shares:
        ncav_total = ca - tl
        m.ncav_per_share = ncav_total / shares
        if price and price > 0:
            m.ncav_to_price = m.ncav_per_share / price

    if m.eps and m.bps and market_cap and ni and ni > 0 and eq and eq > 0:
        per = market_cap / ni
        pbr = market_cap / eq
        m.per_pbr = per * pbr

    # EPS>0 연수 (최신부터 연속)
    pos = 0
    for sf in sf_list:
        n = _g(sf, "controlling_ni") or _g(sf, "net_income")
        if n is not None and n > 0:
            pos += 1
        else:
            break
    m.eps_positive_years = pos

    # ── Greenblatt 마법공식 구성요소 ──
    ebit = _g(curr, "operating_income")
    net_debt = _g(curr, "net_debt") or 0
    if ebit is not None and market_cap:
        ev = market_cap + net_debt
        if ev > 0:
            m.earnings_yield = ebit / ev
    # ROC = EBIT / (순운전자본 + 순고정자산)
    cl = _g(curr, "current_liabilities")
    ppe = _g(curr, "ppe")
    if ebit is not None and ca is not None and cl is not None and ppe is not None:
        nwc = ca - cl
        invested = nwc + ppe
        if invested > 0:
            m.return_on_capital = ebit / invested

    # ── Lynch PEG ──
    if m.eps and market_cap and ni and ni > 0:
        per = market_cap / ni
        ni_prev = _g(prev, "controlling_ni") or _g(prev, "net_income") if prev else None
        if ni_prev and ni_prev > 0:
            growth = (ni - ni_prev) / ni_prev
            if growth > 0:
                m.peg = per / (growth * 100)

    # ── Fisher ──
    rev = _g(curr, "revenue")
    rd = _g(curr, "rd_expense")
    if rd is not None and rev and rev > 0:
        m.rd_to_revenue = rd / rev
    gp = _g(curr, "gross_profit")
    if gp is not None and rev and rev > 0:
        gm_curr = gp / rev
        if prev:
            rev_p = _g(prev, "revenue")
            gp_p = _g(prev, "gross_profit")
            if gp_p is not None and rev_p and rev_p > 0:
                m.gross_margin_delta = gm_curr - (gp_p / rev_p)

    return m
