"""
Rich 터미널 테이블 출력 모듈

사용 예:
    from analyzer.display.table_view import print_analysis
    print_analysis(corp_code="00126380")
"""
from __future__ import annotations

from typing import Optional, List
from datetime import date

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from loguru import logger

console = Console()


def _fmt_amount(value: Optional[int], unit: str = "억원", decimals: int = 0) -> str:
    """금액 포맷 (억원/조원 자동 선택)."""
    if value is None:
        return "—"
    divisor = 1e8 if unit == "억원" else 1e12
    v = value / divisor
    if abs(v) >= 10_000 and unit == "억원":
        return f"{value / 1e12:.1f}조"
    if decimals == 0:
        return f"{v:,.0f}"
    return f"{v:,.{decimals}f}"


def _fmt_pct(value: Optional[float], sign: bool = True) -> str:
    if value is None:
        return "—"
    s = "+" if sign and value > 0 else ""
    color = "green" if value > 0 else "red" if value < 0 else "white"
    return f"[{color}]{s}{value * 100:.1f}%[/{color}]"


def _fmt_ratio(value: Optional[float], suffix: str = "x", decimal: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimal}f}{suffix}"


def print_analysis(
    corp_code: str,
    statement_type: str = "consolidated",
    fiscal_period: str = "FY",
    years: int = 5,
) -> None:
    """종합 재무분석 출력 (Bloomberg-style)."""
    from analyzer.ratio_engine import load_standard_financials, compute_ratios
    from analyzer.valuation_engine import compute_multiples
    from analyzer.buffett_engine import compute_buffett
    from collector.db import get_session
    from sqlalchemy import text

    # 기업 정보
    with get_session() as session:
        corp = session.execute(text(
            "SELECT corp_name, stock_code, market FROM corporations WHERE corp_code = :c"
        ), {"c": corp_code}).fetchone()

    if not corp:
        console.print(f"[red]기업 없음: {corp_code}[/red]")
        return

    corp_name, stock_code, market = corp

    # 재무 데이터 로드
    sf_list = load_standard_financials(corp_code, statement_type, fiscal_period, years)
    if not sf_list:
        # 별도재무제표로 폴백
        sf_list = load_standard_financials(corp_code, "separate", fiscal_period, years)
        if sf_list:
            statement_type = "separate"

    if not sf_list:
        console.print(f"[yellow]{corp_name}: 표준화 재무제표 데이터 없음. 먼저 aggregate 실행[/yellow]")
        return

    curr = sf_list[0]
    prev = sf_list[1] if len(sf_list) > 1 else None

    ratios = compute_ratios(curr, prev)

    # 시총 데이터 (최신 연도 period_end 기준)
    period_end = curr.get("period_end") if isinstance(curr, dict) else getattr(curr, "period_end", None)
    mults = compute_multiples(curr, corp_code, stock_code, period_end)

    buffett = compute_buffett(sf_list, mults.market_cap)

    # ── 헤더 ─────────────────────────────────────────────────────────
    stmt_label = "연결" if statement_type == "consolidated" else "별도"
    title = f"[bold cyan]{corp_name}[/bold cyan] ({stock_code or '비상장'}) — {stmt_label} K-{'IFRS' if curr.get('is_ifrs', True) else 'GAAP'}"
    console.print(Panel(title, box=box.DOUBLE))

    # ── 연도 헤더 ────────────────────────────────────────────────────
    years_labels = [str(sf["fiscal_year"]) for sf in sf_list]

    # ── 손익계산서 테이블 ────────────────────────────────────────────
    _print_is_table(sf_list, years_labels, ratios)

    # ── 재무상태표 테이블 ────────────────────────────────────────────
    _print_bs_table(sf_list, years_labels, ratios)

    # ── 현금흐름 테이블 ──────────────────────────────────────────────
    _print_cf_table(sf_list, years_labels, ratios)

    # ── 밸류에이션 테이블 ────────────────────────────────────────────
    _print_valuation_table(mults, curr, ratios)

    # ── 버핏 관점 지표 ───────────────────────────────────────────────
    _print_buffett_table(buffett)


def _print_is_table(sf_list: list, years: list, ratios) -> None:
    """손익계산서 테이블."""
    table = Table(title="손익계산서 (억원)", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("항목", style="cyan", width=22)
    for y in years:
        table.add_column(y, justify="right", width=12)
    # YoY열 추가
    table.add_column("YoY", justify="right", width=8)

    def _row(label: str, key: str, is_pct: bool = False):
        vals = [sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None) for sf in sf_list]
        cells = [_fmt_amount(v) for v in vals]
        # YoY
        yoy = ""
        if len(vals) >= 2 and vals[0] is not None and vals[1] is not None and vals[1] != 0:
            yoy_val = (vals[0] - vals[1]) / abs(vals[1])
            yoy = _fmt_pct(yoy_val)
        table.add_row(label, *cells, yoy)

    def _pct_row(label: str, key: str, curr_val, prev_val=None):
        """비율 행."""
        cells = []
        for sf in sf_list:
            v = sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None)
            cells.append(f"{v*100:.1f}%" if v is not None else "—")
        table.add_row(label, *cells, "")

    _row("매출액", "revenue")
    _row("매출원가", "cogs")
    _row("매출총이익", "gross_profit")
    _row("판관비", "sga")
    _row("영업이익", "operating_income")
    _row("EBITDA", "ebitda")
    _row("순이익", "net_income")
    _row("지배주주 순이익", "controlling_ni")

    # 마진율
    table.add_section()
    for sf_item in sf_list:
        pass  # 마진율은 비율 계산 필요

    # 마진율 행 (당기만)
    rev = sf_list[0].get("revenue") if isinstance(sf_list[0], dict) else getattr(sf_list[0], "revenue", None)
    if rev and rev > 0:
        def _margin_cells(key):
            cells = []
            for sf in sf_list:
                v = sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None)
                rev_ = sf.get("revenue") if isinstance(sf, dict) else getattr(sf, "revenue", None)
                if v is not None and rev_ and rev_ > 0:
                    cells.append(f"{v/rev_*100:.1f}%")
                else:
                    cells.append("—")
            return cells

        table.add_row("영업이익률", *_margin_cells("operating_income"), "")
        table.add_row("순이익률",   *_margin_cells("net_income"), "")

    console.print(table)


def _print_bs_table(sf_list: list, years: list, ratios) -> None:
    """재무상태표 테이블."""
    table = Table(title="재무상태표 (억원)", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("항목", style="cyan", width=22)
    for y in years:
        table.add_column(y, justify="right", width=12)
    table.add_column("", width=8)

    def _row(label: str, key: str):
        vals = [sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None) for sf in sf_list]
        cells = [_fmt_amount(v) for v in vals]
        table.add_row(label, *cells, "")

    _row("자산총계",     "total_assets")
    _row("유동자산",     "current_assets")
    _row("현금",        "cash")
    _row("매출채권",     "receivables")
    _row("재고자산",     "inventory")
    _row("유형자산",     "ppe")
    _row("무형자산",     "intangibles")
    _row("부채총계",     "total_liabilities")
    _row("유동부채",     "current_liabilities")
    _row("단기차입금",   "short_term_debt")
    _row("장기차입금",   "long_term_debt")
    _row("자본총계",     "total_equity")
    _row("이익잉여금",   "retained_earnings")
    _row("순부채",       "net_debt")

    # 비율
    table.add_section()
    def _ratio_row(label: str, getter):
        cells = []
        for sf in sf_list:
            r = compute_ratios_sf(sf)
            v = getter(r)
            cells.append(_fmt_ratio(v) if v is not None else "—")
        table.add_row(label, *cells, "")

    from analyzer.ratio_engine import compute_ratios

    def compute_ratios_sf(sf):
        return compute_ratios(sf, None)

    table.add_row("부채비율",   *[_fmt_ratio(compute_ratios(sf).debt_ratio) for sf in sf_list], "")
    table.add_row("유동비율",   *[_fmt_ratio(compute_ratios(sf).current_ratio) for sf in sf_list], "")

    console.print(table)


def _print_cf_table(sf_list: list, years: list, ratios) -> None:
    """현금흐름표 테이블."""
    table = Table(title="현금흐름 (억원)", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("항목", style="cyan", width=22)
    for y in years:
        table.add_column(y, justify="right", width=12)
    table.add_column("", width=8)

    def _row(label: str, key: str):
        vals = [sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None) for sf in sf_list]
        cells = [_fmt_amount(v) for v in vals]
        table.add_row(label, *cells, "")

    _row("영업현금흐름(CFO)", "cfo")
    _row("투자현금흐름(CFI)", "cfi")
    _row("재무현금흐름(CFF)", "cff")
    _row("CAPEX",            "capex")
    _row("잉여현금흐름(FCF)", "fcf")
    _row("배당금 지급",       "dividends_paid")
    _row("감가상각비(D&A)",   "da_total")

    console.print(table)


def _print_valuation_table(mults, curr, ratios) -> None:
    """밸류에이션 테이블."""
    table = Table(title="밸류에이션", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("지표", style="cyan", width=20)
    table.add_column("값",   justify="right", width=15)
    table.add_column("비고", width=25)

    def _add(label: str, value: str, note: str = ""):
        table.add_row(label, value, note)

    mc = mults.market_cap
    _add("시가총액",  _fmt_amount(mc, "조원", 1) if mc else "—")
    _add("EV",       _fmt_amount(mults.ev, "조원", 1) if mults.ev else "—",
         "시총 + 순부채")
    _add("PER",      mults.fmt("per"), "주가/EPS")
    _add("PBR",      mults.fmt("pbr"), "주가/BPS")
    _add("PSR",      mults.fmt("psr"), "주가/매출")
    _add("PCR",      mults.fmt("pcr"), "주가/CFO")
    _add("EV/EBITDA", mults.fmt("ev_ebitda"))
    _add("EV/EBIT",  mults.fmt("ev_ebit"),  "영업이익 대비")
    _add("EV/FCF",   mults.fmt("ev_fcf"))

    console.print(table)


def _print_buffett_table(bm) -> None:
    """버핏 관점 지표 테이블."""
    table = Table(title="버핏 관점 지표", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("지표", style="cyan", width=25)
    table.add_column("값",   justify="right", width=15)
    table.add_column("판정", width=20)

    def _add(label: str, value: str, judge: str = ""):
        table.add_row(label, value, judge)

    _add("Owner's Earnings",  bm.oe_in_eok())
    _add("유지CAPEX",          _fmt_amount(bm.maintenance_capex))
    _add("성장CAPEX",          _fmt_amount(bm.growth_capex))

    fq = bm.fcf_quality
    fq_judge = "🟢 우수" if fq and fq > 1.2 else "🟡 보통" if fq and fq > 0.8 else "🔴 약세" if fq else ""
    _add("FCF 품질 (CFO/순이익)", _fmt_ratio(fq, "x", 2), fq_judge)

    ar = bm.accrual_ratio
    ar_judge = "🟢 양호" if ar is not None and ar < -0.02 else \
               "🟡 보통" if ar is not None and ar < 0.03 else \
               "🔴 주의" if ar is not None else ""
    _add("Accrual Ratio",     f"{ar*100:.2f}%" if ar is not None else "—", ar_judge)

    def _fmt_pct_val(v):
        if v is None: return "—"
        return f"{v * 100:.1f}%"

    _add("ROIC (당기)",       _fmt_pct_val(bm.roic), "")
    _add("ROIC 5개년 평균",   _fmt_pct_val(bm.roic_5y_avg))
    _add("ROIC 5개년 편차",   _fmt_pct_val(bm.roic_5y_std), "낮을수록 일관성")

    _add("배당성향",           _fmt_pct_val(bm.payout_ratio))
    _add("Piotroski F-Score", bm.score_badge())

    console.print(table)
