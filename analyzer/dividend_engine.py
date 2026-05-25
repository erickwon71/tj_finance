"""
배당 분석 엔진

standard_financials의 dividends_paid + shares_out + stock_prices.close_price 활용.

사용 예:
    python run.py dividend --corp 00126380
    python run.py dividend --corp 00126380 --years 10
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class DividendYear:
    """연도별 배당 데이터."""
    fiscal_year:   int
    dividends_paid: Optional[int]   # 총 배당 지급액 (원, 양수 저장)
    net_income:    Optional[int]    # 순이익 (원)
    shares_out:    Optional[int]    # 상장주식수
    close_price:   Optional[int]    # 기말 주가 (원)
    dps:           Optional[int]    # 주당배당금 (원)
    div_yield:     Optional[float]  # 배당수익률 (DPS/주가)
    payout_ratio:  Optional[float]  # 배당성향 (총배당/순이익)
    dps_growth:    Optional[float]  # DPS 전년 대비 성장률


@dataclass
class DividendSummary:
    """배당 분석 요약."""
    corp_code:          str
    corp_name:          str
    years:              list[DividendYear]
    consecutive_years:  int           # 연속 배당 연수
    dps_cagr_3y:        Optional[float]
    dps_cagr_5y:        Optional[float]
    avg_yield_3y:       Optional[float]  # 3년 평균 배당수익률
    avg_payout_3y:      Optional[float]  # 3년 평균 배당성향
    total_div_5y:       Optional[int]    # 5년 총 배당액


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _cagr(start, end, n):
    if start and end and start > 0 and end > 0 and n > 0:
        return (end / start) ** (1 / n) - 1
    return None


def analyze_dividend(
    corp_code: str,
    years: int = 10,
    statement_type: str = "consolidated",
) -> Optional[DividendSummary]:
    """
    배당 히스토리 분석.

    Args:
        corp_code:      DART 기업코드
        years:          조회 연수 (기본 10년)
        statement_type: 연결/별도

    Returns:
        DividendSummary 또는 None
    """
    from analyzer.ratio_engine import load_standard_financials
    from collector.db import get_session
    from sqlalchemy import text

    # 재무 데이터 로드 (배당 관련)
    sfs = load_standard_financials(corp_code, statement_type=statement_type,
                                   fiscal_period="FY", years=years)
    if not sfs:
        logger.error(f"재무 데이터 없음: {corp_code}")
        return None

    # 기업 정보
    with get_session() as session:
        row = session.execute(text(
            "SELECT corp_name, stock_code FROM corporations WHERE corp_code = :cc"
        ), {"cc": corp_code}).fetchone()

    corp_name  = row.corp_name if row else corp_code
    stock_code = row.stock_code if row else None

    # 기말 주가 조회 (period_end 기준 ±7일 내 가장 가까운 날)
    price_map: dict[int, int] = {}
    if stock_code:
        with get_session() as session:
            for sf in sfs:
                pe = sf.get("period_end")
                if not pe:
                    continue
                from datetime import timedelta
                price_row = session.execute(text("""
                    SELECT close_price FROM stock_prices
                    WHERE stock_code = :sc
                      AND trade_date BETWEEN :d1 AND :d2
                    ORDER BY ABS(trade_date - :target) ASC LIMIT 1
                """), {
                    "sc":     stock_code,
                    "d1":     pe - timedelta(days=7),
                    "d2":     pe + timedelta(days=7),
                    "target": pe,
                }).fetchone()
                if price_row:
                    price_map[sf["fiscal_year"]] = price_row[0]

    # 연도별 배당 데이터 구성
    div_years: list[DividendYear] = []
    for sf in sfs:
        fy    = sf["fiscal_year"]
        divs  = sf.get("dividends_paid")         # 음수 또는 양수로 저장됨
        ni    = sf.get("net_income")
        so    = sf.get("shares_out")
        price = price_map.get(fy)

        # dividends_paid는 현금유출이므로 음수 저장 → abs()
        total_div = abs(divs) if divs else None

        dps       = int(total_div / so) if total_div and so else None
        div_yield = _safe_div(dps, price)
        payout    = _safe_div(total_div, ni) if ni and ni > 0 else None

        div_years.append(DividendYear(
            fiscal_year    = fy,
            dividends_paid = total_div,
            net_income     = ni,
            shares_out     = so,
            close_price    = price,
            dps            = dps,
            div_yield      = div_yield,
            payout_ratio   = payout,
            dps_growth     = None,   # 아래에서 채움
        ))

    # DPS 전년 대비 성장률
    for i in range(len(div_years) - 1):
        curr_dps = div_years[i].dps
        prev_dps = div_years[i + 1].dps
        if curr_dps is not None and prev_dps and prev_dps > 0:
            div_years[i].dps_growth = (curr_dps - prev_dps) / prev_dps

    # 연속 배당 연수 (최신 연도부터 카운트)
    consecutive = 0
    for dy in div_years:
        if dy.dividends_paid and dy.dividends_paid > 0:
            consecutive += 1
        else:
            break

    # DPS CAGR
    dps_list = [dy.dps for dy in div_years if dy.dps and dy.dps > 0]
    dps_cagr_3y = _cagr(dps_list[3], dps_list[0], 3) if len(dps_list) > 3 else None
    dps_cagr_5y = _cagr(dps_list[5], dps_list[0], 5) if len(dps_list) > 5 else None

    # 3년 평균 배당수익률 / 배당성향
    recent3 = div_years[:3]
    yields  = [dy.div_yield  for dy in recent3 if dy.div_yield  is not None]
    payouts = [dy.payout_ratio for dy in recent3 if dy.payout_ratio is not None]
    avg_yield_3y  = sum(yields)  / len(yields)  if yields  else None
    avg_payout_3y = sum(payouts) / len(payouts) if payouts else None

    # 5년 총 배당액
    divs5 = [dy.dividends_paid for dy in div_years[:5] if dy.dividends_paid]
    total_div_5y = sum(divs5) if divs5 else None

    return DividendSummary(
        corp_code         = corp_code,
        corp_name         = corp_name,
        years             = div_years,
        consecutive_years = consecutive,
        dps_cagr_3y       = dps_cagr_3y,
        dps_cagr_5y       = dps_cagr_5y,
        avg_yield_3y      = avg_yield_3y,
        avg_payout_3y     = avg_payout_3y,
        total_div_5y      = total_div_5y,
    )


def print_dividend(summary: DividendSummary) -> None:
    """배당 분석 결과를 Rich 테이블로 출력."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    console = Console(width=120)

    tbl = Table(
        box=box.SIMPLE_HEAVY, show_header=True, header_style="bold white",
        title=f"배당 분석: {summary.corp_name}",
    )
    tbl.add_column("연도",      width=6)
    tbl.add_column("DPS(원)",   justify="right", width=10)
    tbl.add_column("YoY",       justify="right", width=8)
    tbl.add_column("배당수익률", justify="right", width=9)
    tbl.add_column("배당성향",  justify="right", width=9)
    tbl.add_column("주가(원)",  justify="right", width=10)
    tbl.add_column("총배당(조)", justify="right", width=10)

    def _pct(v):
        return f"{v*100:.1f}%" if v is not None else "—"
    def _pct_chg(v):
        if v is None: return "—"
        c = "green" if v > 0 else ("red" if v < 0 else "white")
        return f"[{c}]{v*100:+.1f}%[/{c}]"
    def _jo(v):
        return f"{v/1e12:.1f}" if v is not None else "—"

    for dy in summary.years:
        dps_str = f"{dy.dps:,}" if dy.dps else "—"
        row_style = ""
        if dy.dividends_paid is None or dy.dividends_paid == 0:
            row_style = "dim"

        tbl.add_row(
            str(dy.fiscal_year),
            dps_str,
            _pct_chg(dy.dps_growth),
            _pct(dy.div_yield),
            _pct(dy.payout_ratio),
            f"{dy.close_price:,}" if dy.close_price else "—",
            _jo(dy.dividends_paid),
            style=row_style,
        )

    console.print(tbl)

    # 요약 패널
    def _fmt_cagr(v):
        if v is None: return "—"
        c = "green" if v > 0 else "red"
        return f"[{c}]{v*100:.1f}%[/{c}]"

    lines = []
    lines.append(f"  연속 배당      [bold]{summary.consecutive_years}년[/bold]")
    lines.append(f"  DPS CAGR 3년   {_fmt_cagr(summary.dps_cagr_3y)}")
    lines.append(f"  DPS CAGR 5년   {_fmt_cagr(summary.dps_cagr_5y)}")
    lines.append(f"  평균 배당수익률(3년)  {_pct(summary.avg_yield_3y)}")
    lines.append(f"  평균 배당성향(3년)   {_pct(summary.avg_payout_3y)}")
    lines.append(f"  5년 총 배당액  {_jo(summary.total_div_5y)}조")

    console.print(Panel("\n".join(lines), title="[bold]배당 요약[/bold]",
                        border_style="green", expand=False))
