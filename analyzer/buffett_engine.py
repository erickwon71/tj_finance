"""
버핏 관점 재무지표 계산

Owner's Earnings, FCF Quality, ROIC 추이, 경영자 자본배분 효율 등

사용 예:
    from analyzer.buffett_engine import compute_buffett
    bm = compute_buffett(sf_list)  # 최근 5년 데이터
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

from analyzer.ratio_engine import _safe_div, _avg


@dataclass
class BuffettMetrics:
    """버핏 관점 지표 컨테이너."""

    # ── Owner's Earnings ────────────────────────────────────────────
    # = 순이익 + D&A - 유지CAPEX
    # 유지CAPEX = min(|CAPEX|, D&A) (보수적 추정)
    owners_earnings:      Optional[int]   = None  # 원
    maintenance_capex:    Optional[int]   = None  # 원
    growth_capex:         Optional[int]   = None  # 원

    # ── FCF 품질 ─────────────────────────────────────────────────────
    # CFO / 순이익  (> 1.0 = 현금 창출 우수)
    fcf_quality:          Optional[float] = None

    # ── ROIC ────────────────────────────────────────────────────────
    roic:                 Optional[float] = None  # 당기
    roic_5y_avg:          Optional[float] = None  # 5개년 평균
    roic_5y_std:          Optional[float] = None  # 5개년 표준편차 (낮을수록 일관성)

    # ── Accrual Ratio (이익 조작 지표) ──────────────────────────────
    # (순이익 - CFO) / 총자산  (< 0 양호)
    accrual_ratio:        Optional[float] = None

    # ── 주주환원 ─────────────────────────────────────────────────────
    payout_ratio:         Optional[float] = None  # 배당성향
    buyback_yield:        Optional[float] = None  # 자사주 매입 수익률 (시총 기준)
    total_shareholder_yield: Optional[float] = None  # 배당 + 자사주 매입

    # ── 자본배분 효율 ─────────────────────────────────────────────────
    retained_roe:         Optional[float] = None  # 유보이익의 ROE (장기 자본효율)

    # ── Piotroski F-Score 구성요소 ────────────────────────────────────
    f_positive_roa:       Optional[int]   = None  # ROA > 0: 1점
    f_positive_cfo:       Optional[int]   = None  # CFO > 0: 1점
    f_accrual:            Optional[int]   = None  # CFO > 순이익: 1점
    f_roa_change:         Optional[int]   = None  # ROA 개선: 1점
    f_lev_change:         Optional[int]   = None  # 부채비율 개선: 1점
    f_liq_change:         Optional[int]   = None  # 유동비율 개선: 1점
    f_no_dilution:        Optional[int]   = None  # 신주 미발행: 1점
    f_margin_change:      Optional[int]   = None  # 매출총이익률 개선: 1점
    f_turnover_change:    Optional[int]   = None  # 자산회전율 개선: 1점
    piotroski_f_score:    Optional[int]   = None  # 합계 (0~9)

    def score_badge(self) -> str:
        """F-Score 등급 뱃지."""
        s = self.piotroski_f_score
        if s is None:
            return "—"
        if s >= 8:
            return f"🟢 강세 ({s}/9)"
        if s >= 6:
            return f"🟡 양호 ({s}/9)"
        if s >= 4:
            return f"🟠 보통 ({s}/9)"
        return f"🔴 약세 ({s}/9)"

    def oe_in_eok(self) -> str:
        """Owner's Earnings 억원 단위."""
        if self.owners_earnings is None:
            return "—"
        return f"{self.owners_earnings/1e8:.0f}억원"


def compute_buffett(
    sf_list: list,        # [당기, 전기, 전전기, ...] StandardFinancial 또는 dict
    market_cap: Optional[int] = None,
) -> BuffettMetrics:
    """
    버핏 관점 지표 계산.

    Args:
        sf_list: 연도 내림차순 (최신이 sf_list[0])
        market_cap: 시가총액 (배당수익률/자사주수익률 계산용)
    """
    if not sf_list:
        return BuffettMetrics()

    def _get(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    curr = sf_list[0]
    prev = sf_list[1] if len(sf_list) > 1 else None

    bm = BuffettMetrics()

    # ── Owner's Earnings ────────────────────────────────────────────
    ni    = _get(curr, "net_income")
    da    = _get(curr, "da_total")
    capex = _get(curr, "capex")
    cfo   = _get(curr, "cfo")

    if ni is not None and da is not None and capex is not None:
        abs_capex = abs(capex)
        bm.maintenance_capex = min(abs_capex, da)
        bm.growth_capex      = abs_capex - bm.maintenance_capex
        bm.owners_earnings   = ni + da - bm.maintenance_capex

    # ── FCF 품질 ─────────────────────────────────────────────────────
    if cfo is not None and ni and ni != 0:
        bm.fcf_quality = cfo / ni

    # ── Accrual Ratio ────────────────────────────────────────────────
    ta = _get(curr, "total_assets")
    if ni is not None and cfo is not None and ta and ta > 0:
        bm.accrual_ratio = (ni - cfo) / ta

    # ── ROIC (당기) ──────────────────────────────────────────────────
    from analyzer.ratio_engine import compute_ratios
    ratios_curr = compute_ratios(curr, prev)
    bm.roic = ratios_curr.roic

    # ── ROIC 다년도 추이 ─────────────────────────────────────────────
    roic_list = []
    for i in range(len(sf_list)):
        r_sf   = sf_list[i]
        r_prev = sf_list[i + 1] if i + 1 < len(sf_list) else None
        r      = compute_ratios(r_sf, r_prev)
        if r.roic is not None:
            roic_list.append(r.roic)

    if len(roic_list) >= 2:
        bm.roic_5y_avg = statistics.mean(roic_list)
        bm.roic_5y_std = statistics.stdev(roic_list) if len(roic_list) >= 2 else None

    # ── 주주환원 ─────────────────────────────────────────────────────
    div_paid = _get(curr, "dividends_paid")
    if ni and ni > 0 and div_paid is not None:
        bm.payout_ratio = abs(div_paid) / ni

    # ── Piotroski F-Score ────────────────────────────────────────────
    bm.piotroski_f_score = _calc_piotroski(sf_list, ratios_curr)

    return bm


def _calc_piotroski(sf_list: list, ratios_curr) -> Optional[int]:
    """Piotroski F-Score (0~9) 계산."""
    if not sf_list:
        return None

    def _get(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    curr = sf_list[0]
    prev = sf_list[1] if len(sf_list) > 1 else None

    from analyzer.ratio_engine import compute_ratios, _safe_div
    ratios_prev = compute_ratios(prev, None) if prev else None

    score = 0
    filled = 0   # 계산 가능한 항목 수

    # F1: ROA > 0
    roa = ratios_curr.roa
    if roa is not None:
        filled += 1
        if roa > 0:
            score += 1

    # F2: CFO > 0
    cfo = _get(curr, "cfo")
    if cfo is not None:
        filled += 1
        if cfo > 0:
            score += 1

    # F3: CFO > 순이익 (Accruals 양호)
    ni = _get(curr, "net_income")
    if cfo is not None and ni is not None:
        filled += 1
        if cfo > ni:
            score += 1

    # F4: ROA 개선
    if roa is not None and ratios_prev and ratios_prev.roa is not None:
        filled += 1
        if roa > ratios_prev.roa:
            score += 1

    # F5: 부채비율 개선 (감소)
    dr = ratios_curr.debt_ratio
    dr_p = ratios_prev.debt_ratio if ratios_prev else None
    if dr is not None and dr_p is not None:
        filled += 1
        if dr < dr_p:
            score += 1

    # F6: 유동비율 개선
    cr = ratios_curr.current_ratio
    cr_p = ratios_prev.current_ratio if ratios_prev else None
    if cr is not None and cr_p is not None:
        filled += 1
        if cr > cr_p:
            score += 1

    # F7: 신주 미발행 (주식수 불변 또는 감소)
    so_curr = _get(curr, "shares_out")
    so_prev = _get(prev, "shares_out") if prev else None
    if so_curr is not None and so_prev is not None:
        filled += 1
        if so_curr <= so_prev:
            score += 1
    else:
        # fallback: paid_in_capital 변화로 추정 (자본금 증가 없으면 +1)
        pic_curr = _get(curr, "paid_in_capital")
        pic_prev = _get(prev, "paid_in_capital") if prev else None
        if pic_curr is not None and pic_prev is not None:
            filled += 1
            if pic_curr <= pic_prev * 1.01:  # 1% 허용 오차
                score += 1

    # F8: 매출총이익률 개선
    gm = ratios_curr.gross_margin
    gm_p = ratios_prev.gross_margin if ratios_prev else None
    if gm is not None and gm_p is not None:
        filled += 1
        if gm > gm_p:
            score += 1

    # F9: 자산회전율 개선
    at = ratios_curr.asset_turnover
    at_p = ratios_prev.asset_turnover if ratios_prev else None
    if at is not None and at_p is not None:
        filled += 1
        if at > at_p:
            score += 1

    # 최소 5개 항목이 계산되어야 신뢰할 수 있음
    if filled < 5:
        return None

    return score
