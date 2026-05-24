"""
재무비율 계산 엔진

입력: StandardFinancial 행 (또는 같은 필드를 가진 dict)
출력: FinancialRatios 네임드튜플 (수익성/안정성/효율성/성장성)

사용 예:
    from analyzer.ratio_engine import compute_ratios
    ratios = compute_ratios(sf_curr, sf_prev)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── 안전 나눗셈 ─────────────────────────────────────────────────────────────
def _safe_div(numerator, denominator, default=None):
    """분모 0/None이면 default 반환."""
    if numerator is None or denominator is None:
        return default
    if denominator == 0:
        return default
    return numerator / denominator


def _avg(*values):
    """None 제외 평균. 모두 None이면 None."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _growth_rate(curr, prev) -> Optional[float]:
    """전기 대비 성장률. 전기가 0이거나 음수이면 None."""
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def _cagr(start, end, years: int) -> Optional[float]:
    """CAGR (연복리성장률)."""
    if start is None or end is None or years <= 0 or start <= 0:
        return None
    return (end / start) ** (1 / years) - 1


@dataclass
class FinancialRatios:
    """계산된 재무비율 컨테이너."""

    # ── 수익성 ──────────────────────────────────────────────────────
    gross_margin:      Optional[float] = None  # 매출총이익률
    op_margin:         Optional[float] = None  # 영업이익률
    net_margin:        Optional[float] = None  # 순이익률
    ebitda_margin:     Optional[float] = None  # EBITDA 마진
    roe:               Optional[float] = None  # 자기자본이익률
    roa:               Optional[float] = None  # 총자산이익률
    roic:              Optional[float] = None  # 투하자본이익률
    asset_turnover:    Optional[float] = None  # 자산회전율 (DuPont)

    # ── 재무건전성 ───────────────────────────────────────────────────
    debt_ratio:         Optional[float] = None  # 부채비율 (부채/자본)
    current_ratio:      Optional[float] = None  # 유동비율
    interest_coverage:  Optional[float] = None  # 이자보상배율
    net_debt_ebitda:    Optional[float] = None  # 순부채/EBITDA

    # ── CAPEX / FCF ─────────────────────────────────────────────────
    capex_to_revenue:   Optional[float] = None  # CAPEX / 매출
    capex_to_dep:       Optional[float] = None  # CAPEX / 감가상각비
    fcf:                Optional[int]   = None  # 잉여현금흐름 (원)
    fcf_to_revenue:     Optional[float] = None  # FCF / 매출

    # ── 이익 품질 (Sloan) ────────────────────────────────────────────
    cfo_to_ni:          Optional[float] = None  # CFO / 순이익 (> 1 = 우수)
    accrual_ratio:      Optional[float] = None  # (순이익 - CFO) / 총자산 (< 0 = 양호)

    # ── 운전자본 효율 ─────────────────────────────────────────────────
    dso:                Optional[float] = None  # Days Sales Outstanding
    dio:                Optional[float] = None  # Days Inventory Outstanding
    dpo:                Optional[float] = None  # Days Payable Outstanding
    ccc:                Optional[float] = None  # Cash Conversion Cycle

    # ── 성장성 ──────────────────────────────────────────────────────
    revenue_growth:     Optional[float] = None  # 매출 YoY
    op_income_growth:   Optional[float] = None  # 영업이익 YoY
    net_income_growth:  Optional[float] = None  # 순이익 YoY
    asset_growth:       Optional[float] = None  # 총자산 YoY

    # ── 세율 추정 ────────────────────────────────────────────────────
    effective_tax_rate: Optional[float] = None  # 법인세비용 / 세전이익

    # ── NOPAT / 투하자본 (ROIC용) ────────────────────────────────────
    nopat:              Optional[int]   = None  # Net Operating Profit After Tax
    invested_capital:   Optional[int]   = None  # 총자본 + 순부채

    def as_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    def pct(self, attr: str) -> str:
        """비율을 % 문자열로 변환."""
        v = getattr(self, attr, None)
        if v is None:
            return "—"
        return f"{v * 100:.1f}%"

    def x(self, attr: str, decimal: int = 1) -> str:
        """배수/회전율 문자열."""
        v = getattr(self, attr, None)
        if v is None:
            return "—"
        return f"{v:.{decimal}f}x"


def compute_ratios(
    curr,           # StandardFinancial 또는 dict (당기)
    prev=None,      # StandardFinancial 또는 dict (전기, 성장률 계산용)
) -> FinancialRatios:
    """
    재무비율 계산.

    Args:
        curr: 당기 StandardFinancial 또는 동일 필드를 가진 dict/네임드튜플
        prev: 전기 데이터 (성장률, 평균 계산용). None이면 성장률은 모두 None
    """

    def _get(obj, attr, default=None):
        """obj가 dict면 .get(), 아니면 getattr()"""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    # ── 기본 값 추출 ───────────────────────────────────────────────
    rev    = _get(curr, "revenue")
    cogs   = _get(curr, "cogs")
    gross  = _get(curr, "gross_profit")
    op     = _get(curr, "operating_income")
    ebitda = _get(curr, "ebitda")
    ni     = _get(curr, "net_income")
    ebt    = _get(curr, "ebt")
    tax    = _get(curr, "tax_expense")
    int_ex = _get(curr, "interest_expense")
    cfo    = _get(curr, "cfo")
    capex  = _get(curr, "capex")
    da     = _get(curr, "da_total")
    fcf    = _get(curr, "fcf")

    ta     = _get(curr, "total_assets")
    ca     = _get(curr, "current_assets")
    cl     = _get(curr, "current_liabilities")
    tl     = _get(curr, "total_liabilities")
    eq     = _get(curr, "total_equity")
    ceq    = _get(curr, "controlling_equity")
    re     = _get(curr, "receivables")
    inv    = _get(curr, "inventory")
    pay    = _get(curr, "trade_payables")
    cash   = _get(curr, "cash")
    net_dt = _get(curr, "net_debt")

    # 전기 값 (성장률 계산용)
    rev_p  = _get(prev, "revenue")
    op_p   = _get(prev, "operating_income")
    ni_p   = _get(prev, "net_income")
    ta_p   = _get(prev, "total_assets")
    eq_p   = _get(prev, "total_equity")

    r = FinancialRatios()

    # ── 수익성 ─────────────────────────────────────────────────────
    r.gross_margin    = _safe_div(gross, rev)
    r.op_margin       = _safe_div(op, rev)
    r.net_margin      = _safe_div(ni, rev)
    r.ebitda_margin   = _safe_div(ebitda, rev)

    avg_eq  = _avg(eq, eq_p)
    avg_ta  = _avg(ta, ta_p)
    r.roe           = _safe_div(ni, avg_eq)
    r.roa           = _safe_div(ni, avg_ta)
    r.asset_turnover = _safe_div(rev, avg_ta)

    # ── 세율 / ROIC ─────────────────────────────────────────────────
    r.effective_tax_rate = _safe_div(tax, ebt) if ebt and ebt > 0 else None
    tax_rate = r.effective_tax_rate or 0.22   # fallback: 법인세율 22%

    if op is not None:
        r.nopat = int(op * (1 - tax_rate))
        net_debt_val = net_dt if net_dt is not None else 0
        r.invested_capital = (eq or 0) + net_debt_val
        r.roic = _safe_div(r.nopat, r.invested_capital)

    # ── 재무건전성 ───────────────────────────────────────────────────
    r.debt_ratio        = _safe_div(tl, eq)
    r.current_ratio     = _safe_div(ca, cl)
    r.interest_coverage = _safe_div(op, abs(int_ex)) if int_ex else None
    r.net_debt_ebitda   = _safe_div(net_dt, ebitda) if ebitda and ebitda > 0 else None

    # ── CAPEX / FCF ─────────────────────────────────────────────────
    if capex is not None:
        abs_capex = abs(capex)
        r.capex_to_revenue = _safe_div(abs_capex, rev)
        r.capex_to_dep     = _safe_div(abs_capex, da) if da else None

    r.fcf = fcf
    r.fcf_to_revenue = _safe_div(fcf, rev) if fcf is not None else None

    # ── 이익 품질 ────────────────────────────────────────────────────
    r.cfo_to_ni     = _safe_div(cfo, ni) if ni else None
    if ni is not None and cfo is not None and ta:
        r.accrual_ratio = (ni - cfo) / ta

    # ── 운전자본 효율 ─────────────────────────────────────────────────
    if rev:
        r.dso = _safe_div((re or 0) * 365, rev)
    if cogs:
        r.dio = _safe_div((inv or 0) * 365, cogs)
        r.dpo = _safe_div((pay or 0) * 365, cogs)
    if r.dso is not None and r.dio is not None and r.dpo is not None:
        r.ccc = r.dso + r.dio - r.dpo

    # ── 성장성 ──────────────────────────────────────────────────────
    r.revenue_growth    = _growth_rate(rev, rev_p)
    r.op_income_growth  = _growth_rate(op, op_p)
    r.net_income_growth = _growth_rate(ni, ni_p)
    r.asset_growth      = _growth_rate(ta, ta_p)

    return r


def load_standard_financials(
    corp_code: str,
    statement_type: str = "consolidated",
    fiscal_period: str = "FY",
    years: int = 5,
) -> list:
    """
    standard_financials에서 최근 N년치 데이터를 조회.

    Returns:
        연도 내림차순 리스트 (최신 → 과거)
    """
    from collector.db import get_session
    from sqlalchemy import text

    sql = """
        SELECT *
        FROM standard_financials
        WHERE corp_code      = :corp
          AND statement_type = :stype
          AND fiscal_period  = :fp
        ORDER BY fiscal_year DESC
        LIMIT :n
    """
    with get_session() as session:
        rows = session.execute(text(sql), {
            "corp": corp_code, "stype": statement_type,
            "fp": fiscal_period, "n": years,
        }).mappings().fetchall()

    return [dict(r) for r in rows]
