"""
DCF 모델 — 내재가치 + 안전마진 계산

FCF 기반 할인현금흐름:
  1. WACC 추정: CAPM (베타 × ERP) + 부채비용
  2. FCF 성장률: 역사적 CAGR 또는 수동 입력 (상한 20%)
  3. Terminal Value: Gordon Growth Model
  4. 주당 적정가 / 현재 주가 / 안전마진

사용 예:
    python run.py dcf --corp 00126380
    python run.py dcf --corp 00126380 --growth 8% --wacc 10% --terminal 3%
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


# ── 기본 가정 상수 ────────────────────────────────────────────────────────────
_RISK_FREE_RATE  = 0.035   # 한국 국고채 10년 기준금리 (~3.5%)
_ERP             = 0.055   # 한국 주식시장 위험프리미엄 (5.5%)
_DEFAULT_BETA    = 1.0     # 베타 계산 실패 시 기본값
_TERMINAL_GROWTH = 0.025   # 영구성장률 기본값 (2.5%)
_DCF_YEARS       = 5       # 예측 기간 (년)
_MAX_FCF_GROWTH  = 0.20    # FCF 성장률 상한 (20%)
_MIN_FCF_GROWTH  = -0.10   # FCF 성장률 하한 (-10%)


@dataclass
class DCFResult:
    """DCF 계산 결과."""
    corp_code:       str
    corp_name:       str
    fiscal_year:     int
    base_fcf:        Optional[int]       # 기준 FCF (원)
    fcf_growth:      float               # FCF 성장률
    wacc:            float               # 할인율
    terminal_growth: float               # 영구성장률
    beta:            float
    risk_free_rate:  float
    erp:             float
    cost_of_equity:  float
    cost_of_debt:    Optional[float]
    tax_rate:        float
    projected_fcfs:  list[tuple[int, int, int]]  # [(year, fcf, pv), ...]
    terminal_value:  int                 # 영구가치 (원)
    terminal_value_pv: int               # 영구가치 PV (원)
    enterprise_value:  int               # 기업가치
    net_debt:          int               # 순부채 (순현금이면 음수)
    equity_value:      int               # 자기자본 가치
    shares_out:        Optional[int]     # 상장주식수
    intrinsic_per_share: Optional[int]   # 주당 적정가
    current_price:     Optional[int]     # 현재 주가
    safety_margin:     Optional[float]   # 안전마진 (intrinsic 대비)
    fcf_cagr_3y:       Optional[float]   # 3년 FCF CAGR
    fcf_cagr_5y:       Optional[float]   # 5년 FCF CAGR
    growth_source:     str               # "3Y CAGR" / "5Y CAGR" / "수동입력"


# ── 베타 계산 ─────────────────────────────────────────────────────────────────

def _calc_beta(stock_code: str, days: int = 252) -> float:
    """
    pykrx로 주가/KOSPI 일별 수익률 계산 → 베타 반환.
    실패 시 _DEFAULT_BETA(1.0) 반환.
    """
    try:
        import numpy as np
        from pykrx import stock as krx
        from datetime import date, timedelta

        end   = date.today()
        start = end - timedelta(days=days + 30)  # 여유 포함
        s = start.strftime("%Y%m%d")
        e = end.strftime("%Y%m%d")

        # 종목 일별 종가
        df_stock = krx.get_market_ohlcv(s, e, stock_code)["종가"]
        # KOSPI 일별 종가 (인덱스코드 1001)
        df_kospi = krx.get_index_ohlcv_by_date(s, e, "1001")["종가"]

        # 공통 날짜로 정렬
        common = df_stock.index.intersection(df_kospi.index)
        if len(common) < 60:
            return _DEFAULT_BETA

        rs = df_stock[common].pct_change().dropna()
        rm = df_kospi[common].pct_change().dropna()
        common2 = rs.index.intersection(rm.index)
        rs = rs[common2].values
        rm = rm[common2].values

        cov = np.cov(rs, rm)
        beta = cov[0, 1] / cov[1, 1]
        return max(0.3, min(3.0, beta))   # 0.3~3.0 클램핑

    except Exception as e:
        logger.debug(f"베타 계산 실패 [{stock_code}]: {e}")
        return _DEFAULT_BETA


# ── WACC 추정 ─────────────────────────────────────────────────────────────────

def _estimate_wacc(
    curr: dict,
    beta: float,
    risk_free_rate: float = _RISK_FREE_RATE,
    erp: float = _ERP,
    market_cap: Optional[int] = None,
) -> tuple[float, Optional[float], float, float]:
    """
    WACC 계산.

    Returns:
        (wacc, cost_of_debt, cost_of_equity, effective_tax_rate)
    """
    def _g(k, d=None):
        v = curr.get(k)
        return v if v is not None else d

    # 자기자본 비용 (CAPM)
    cost_of_equity = risk_free_rate + beta * erp

    # 부채비용
    int_exp    = abs(_g("interest_expense") or 0)
    std        = abs(_g("short_term_debt") or 0)
    ltd        = abs(_g("long_term_debt") or 0)
    total_debt = std + ltd
    cost_of_debt = (int_exp / total_debt) if total_debt > 0 else 0.045  # fallback 4.5%
    cost_of_debt = max(0.02, min(0.12, cost_of_debt))  # 2~12% 범위

    # 세율
    ebt = _g("ebt")
    tax = _g("tax_expense")
    if ebt and ebt > 0 and tax and tax > 0:
        tax_rate = min(tax / ebt, 0.35)
    else:
        tax_rate = 0.22  # 법인세 기본 22%

    # 자본구조 가중치
    mktcap = market_cap or 0
    if mktcap > 0 and total_debt > 0:
        total_cap = mktcap + total_debt
        we = mktcap / total_cap
        wd = total_debt / total_cap
    else:
        we, wd = 0.85, 0.15  # 자본 중심 기업 기본값

    wacc = we * cost_of_equity + wd * cost_of_debt * (1 - tax_rate)
    return wacc, cost_of_debt, cost_of_equity, tax_rate


# ── FCF 성장률 계산 ───────────────────────────────────────────────────────────

def _calc_fcf_cagr(sfs: list, years: int) -> Optional[float]:
    """
    FCF N년 CAGR 계산. sfs는 최신→과거 순.
    음수 FCF 포함 시 None 반환.
    """
    if len(sfs) <= years:
        return None
    base = sfs[years].get("fcf")
    last = sfs[0].get("fcf")
    if not base or not last or base <= 0 or last <= 0:
        return None
    return (last / base) ** (1 / years) - 1


def _choose_fcf_growth(
    sfs: list,
    user_growth: Optional[float] = None,
) -> tuple[float, str]:
    """
    FCF 성장률 선택.

    우선순위:
      1. 사용자 수동 입력
      2. 5년 CAGR (기간 충분 시)
      3. 3년 CAGR
      4. 최근 1년 FCF 성장률 (보수적으로 절반)
      5. 기본값 5%
    """
    if user_growth is not None:
        return user_growth, "수동입력"

    cagr5 = _calc_fcf_cagr(sfs, 5)
    cagr3 = _calc_fcf_cagr(sfs, 3)

    if cagr5 is not None:
        g = max(_MIN_FCF_GROWTH, min(_MAX_FCF_GROWTH, cagr5))
        return g, "5Y CAGR"
    if cagr3 is not None:
        g = max(_MIN_FCF_GROWTH, min(_MAX_FCF_GROWTH, cagr3))
        return g, "3Y CAGR"

    # FCF가 음수라도 CFO 기반 추정
    if len(sfs) >= 2:
        cfo0 = sfs[0].get("cfo")
        cfo1 = sfs[1].get("cfo")
        if cfo0 and cfo1 and cfo1 > 0:
            g = max(_MIN_FCF_GROWTH, min(0.10, (cfo0 / cfo1 - 1) * 0.5))
            return g, "CFO 성장 절반"

    return 0.05, "기본값(5%)"


# ── 메인 DCF 계산 ─────────────────────────────────────────────────────────────

def run_dcf(
    corp_code: str,
    user_growth:   Optional[float] = None,  # 예: 0.08 = 8%
    user_wacc:     Optional[float] = None,  # 예: 0.10 = 10%
    terminal_growth: float = _TERMINAL_GROWTH,
    dcf_years:     int   = _DCF_YEARS,
    risk_free_rate: float = _RISK_FREE_RATE,
    erp:           float = _ERP,
    statement_type: str  = "consolidated",
) -> Optional[DCFResult]:
    """
    DCF 모델 실행.

    Args:
        corp_code:       DART 기업코드
        user_growth:     FCF 성장률 수동 입력 (None=자동)
        user_wacc:       WACC 수동 입력 (None=자동)
        terminal_growth: 영구성장률 (기본 2.5%)
        dcf_years:       예측 기간 (기본 5년)
        risk_free_rate:  무위험수익률 (기본 3.5%)
        erp:             주식위험프리미엄 (기본 5.5%)
    """
    from analyzer.ratio_engine import load_standard_financials
    from analyzer.price_fetcher import get_market_data
    from collector.db import get_session
    from sqlalchemy import text

    # ── 데이터 로드 ──────────────────────────────────────────────────
    sfs = load_standard_financials(corp_code, statement_type=statement_type,
                                   fiscal_period="FY", years=8)
    if not sfs:
        logger.error(f"재무 데이터 없음: {corp_code}")
        return None

    curr = sfs[0]
    base_fcf = curr.get("fcf")
    if not base_fcf:
        logger.warning(f"FCF 데이터 없음 — CFO 기반으로 추정합니다.")
        cfo   = curr.get("cfo") or 0
        capex = abs(curr.get("capex") or 0)
        base_fcf = cfo - capex
        if base_fcf <= 0:
            logger.error(f"FCF/CFO 모두 음수 또는 없음 → DCF 계산 불가")
            return None

    # ── 기업 기본 정보 ───────────────────────────────────────────────
    with get_session() as session:
        row = session.execute(text(
            "SELECT corp_name, stock_code FROM corporations WHERE corp_code = :cc"
        ), {"cc": corp_code}).fetchone()

    corp_name  = row.corp_name if row else corp_code
    stock_code = row.stock_code if row else None

    # ── 주가 / 주식수 ────────────────────────────────────────────────
    from datetime import date
    current_price = None
    shares_out    = curr.get("shares_out")

    if stock_code:
        mdata = get_market_data(stock_code, as_of_date=date.today(),
                                corp_code=corp_code)
        if mdata:
            current_price = mdata.get("close_price")
            if not shares_out:
                shares_out = mdata.get("shares_out")

    market_cap = (current_price * shares_out) if current_price and shares_out else None

    # ── 베타 / WACC ──────────────────────────────────────────────────
    beta = _calc_beta(stock_code) if stock_code else _DEFAULT_BETA
    logger.debug(f"베타: {beta:.2f}")

    if user_wacc is not None:
        wacc = user_wacc
        cost_of_debt   = None
        cost_of_equity = risk_free_rate + beta * erp
        tax_rate       = 0.22
    else:
        wacc, cost_of_debt, cost_of_equity, tax_rate = _estimate_wacc(
            curr, beta, risk_free_rate, erp, market_cap
        )

    # WACC > terminal_growth 보장
    if wacc <= terminal_growth:
        terminal_growth = wacc - 0.01
        logger.warning(f"WACC({wacc:.1%}) ≤ terminal_growth → 자동 조정: {terminal_growth:.1%}")

    # ── FCF 성장률 ───────────────────────────────────────────────────
    fcf_cagr_3y = _calc_fcf_cagr(sfs, 3)
    fcf_cagr_5y = _calc_fcf_cagr(sfs, 5)
    fcf_growth, growth_source = _choose_fcf_growth(sfs, user_growth)

    # ── FCF 예측 + PV 계산 ───────────────────────────────────────────
    projected_fcfs = []
    base_year = curr.get("fiscal_year", date.today().year)
    for n in range(1, dcf_years + 1):
        fcf_n = int(base_fcf * (1 + fcf_growth) ** n)
        pv_n  = int(fcf_n / (1 + wacc) ** n)
        projected_fcfs.append((base_year + n, fcf_n, pv_n))

    pv_sum = sum(pv for _, _, pv in projected_fcfs)

    # ── Terminal Value ───────────────────────────────────────────────
    fcf_last  = projected_fcfs[-1][1]
    tv        = int(fcf_last * (1 + terminal_growth) / (wacc - terminal_growth))
    tv_pv     = int(tv / (1 + wacc) ** dcf_years)

    # ── 가치 평가 ────────────────────────────────────────────────────
    enterprise_value = pv_sum + tv_pv
    net_debt         = curr.get("net_debt") or 0
    equity_value     = enterprise_value - net_debt

    intrinsic_per_share = None
    safety_margin       = None
    if shares_out and shares_out > 0:
        intrinsic_per_share = int(equity_value / shares_out)
        if current_price and intrinsic_per_share > 0:
            safety_margin = (intrinsic_per_share - current_price) / intrinsic_per_share

    return DCFResult(
        corp_code        = corp_code,
        corp_name        = corp_name,
        fiscal_year      = base_year,
        base_fcf         = base_fcf,
        fcf_growth       = fcf_growth,
        wacc             = wacc,
        terminal_growth  = terminal_growth,
        beta             = beta,
        risk_free_rate   = risk_free_rate,
        erp              = erp,
        cost_of_equity   = cost_of_equity,
        cost_of_debt     = cost_of_debt,
        tax_rate         = tax_rate,
        projected_fcfs   = projected_fcfs,
        terminal_value   = tv,
        terminal_value_pv = tv_pv,
        enterprise_value = enterprise_value,
        net_debt         = net_debt,
        equity_value     = equity_value,
        shares_out       = shares_out,
        intrinsic_per_share = intrinsic_per_share,
        current_price    = current_price,
        safety_margin    = safety_margin,
        fcf_cagr_3y      = fcf_cagr_3y,
        fcf_cagr_5y      = fcf_cagr_5y,
        growth_source    = growth_source,
    )


# ── 출력 ─────────────────────────────────────────────────────────────────────

def print_dcf(result: DCFResult) -> None:
    """DCF 결과를 Rich 패널로 출력."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box

    console = Console(width=100)

    def _jo(v):
        if v is None: return "—"
        return f"{v/1e12:.1f}조"
    def _won(v):
        if v is None: return "—"
        return f"{v:,}원"
    def _pct(v):
        if v is None: return "—"
        return f"{v*100:.1f}%"

    # 안전마진 판정
    sm = result.safety_margin
    if sm is None:
        sm_label = "—"
        sm_color = "white"
    elif sm >= 0.30:
        sm_label = f"{sm*100:.1f}%  🟢 매력적"
        sm_color = "green"
    elif sm >= 0.15:
        sm_label = f"{sm*100:.1f}%  🟡 적정"
        sm_color = "yellow"
    elif sm >= 0:
        sm_label = f"{sm*100:.1f}%  🟠 소폭 저평가"
        sm_color = "yellow"
    else:
        sm_label = f"{sm*100:.1f}%  🔴 과대평가"
        sm_color = "red"

    lines = []
    lines.append(f"[bold]기업[/bold]       {result.corp_name} ({result.corp_code})")
    lines.append(f"[bold]기준 연도[/bold]  {result.fiscal_year} FY")
    lines.append("")

    # 가정
    lines.append("[bold yellow]─ 가정 ─────────────────────────────────────────[/bold yellow]")
    cagr3 = f"{result.fcf_cagr_3y*100:.1f}%" if result.fcf_cagr_3y else "—"
    cagr5 = f"{result.fcf_cagr_5y*100:.1f}%" if result.fcf_cagr_5y else "—"
    lines.append(f"  FCF 성장률      {result.fcf_growth*100:.1f}%  ({result.growth_source}  3Y:{cagr3} / 5Y:{cagr5})")
    lines.append(f"  WACC            {result.wacc*100:.1f}%  (Rf {result.risk_free_rate*100:.1f}% + β{result.beta:.2f}×ERP{result.erp*100:.1f}%)")
    lines.append(f"  자기자본비용    {result.cost_of_equity*100:.1f}%")
    if result.cost_of_debt:
        lines.append(f"  부채비용        {result.cost_of_debt*100:.1f}%  (세전)")
    lines.append(f"  영구성장률      {result.terminal_growth*100:.1f}%")
    lines.append(f"  기준 FCF        {_jo(result.base_fcf)}")
    lines.append("")

    # FCF 예측 테이블
    lines.append("[bold yellow]─ FCF 예측 ──────────────────────────────────────[/bold yellow]")

    tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim",
                padding=(0, 1), min_width=50)
    tbl.add_column("연도", justify="center", width=6)
    tbl.add_column("예측 FCF", justify="right", width=10)
    tbl.add_column("현재가치 (PV)", justify="right", width=13)

    for yr, fcf, pv in result.projected_fcfs:
        tbl.add_row(str(yr), _jo(fcf), _jo(pv))

    tbl.add_row("", "", "")
    tbl.add_row("[dim]Terminal Value[/dim]",
                _jo(result.terminal_value),
                f"[bold]{_jo(result.terminal_value_pv)}[/bold]")

    # 가치 평가 요약
    lines2 = []
    lines2.append("[bold yellow]─ 가치 평가 ─────────────────────────────────────[/bold yellow]")
    tv_ratio = result.terminal_value_pv / result.enterprise_value * 100 if result.enterprise_value else 0
    lines2.append(f"  기업가치 (EV)   [bold]{_jo(result.enterprise_value)}[/bold]  (TV 비중 {tv_ratio:.0f}%)")
    nd_label = f"순부채 {_jo(result.net_debt)}" if result.net_debt > 0 else f"순현금 {_jo(abs(result.net_debt))}"
    lines2.append(f"  {nd_label}")
    lines2.append(f"  자기자본 가치   [bold]{_jo(result.equity_value)}[/bold]")
    if result.shares_out:
        lines2.append(f"  상장주식수      {result.shares_out/1e8:.2f}억주")
    lines2.append("")
    lines2.append(f"  주당 적정가     [bold]{_won(result.intrinsic_per_share)}[/bold]")
    lines2.append(f"  현재 주가       {_won(result.current_price)}")
    lines2.append(f"  안전마진        [{sm_color}]{sm_label}[/{sm_color}]")
    lines2.append("")
    lines2.append("[dim]⚠ DCF는 가정에 민감합니다. 참고용으로 활용하세요.[/dim]")

    all_text = "\n".join(lines)
    all_text2 = "\n".join(lines2)

    console.print(Panel(all_text, title=f"[bold]DCF 분석: {result.corp_name}[/bold]",
                        border_style="blue", expand=False))
    console.print(tbl)
    console.print(Panel(all_text2, title="[bold]가치 평가[/bold]",
                        border_style="blue", expand=False))
