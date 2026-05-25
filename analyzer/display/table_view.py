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


def _period_label(sf: dict) -> str:
    """분기/반기/연간 레이블. 예: '2024 FY', '2024 H1', '2024 Q1', '2023 Q3'."""
    fy = sf.get("fiscal_year", "?")
    fp = sf.get("fiscal_period", "FY")
    fp_map = {"FY": "FY", "H1": "H1", "Q1": "Q1", "Q3": "Q3"}
    return f"{fy} {fp_map.get(fp, fp)}"


def print_analysis(
    corp_code: str,
    statement_type: str = "consolidated",
    fiscal_period: str = "FY",
    years: int = 5,
) -> None:
    """종합 재무분석 출력 (Bloomberg-style).

    Args:
        fiscal_period: "FY"=연간(기본) / "ALL"=분기혼합 / "HALF"=반기
    """
    from analyzer.ratio_engine import load_standard_financials, compute_ratios
    from analyzer.valuation_engine import compute_multiples
    from analyzer.buffett_engine import compute_buffett
    from collector.db import get_session
    from sqlalchemy import text

    is_multi_period = fiscal_period in ("ALL", "HALF")

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
    period_mode_label = {
        "ALL":  " │ [yellow]분기별 (YTD)[/yellow]",
        "HALF": " │ [yellow]반기별[/yellow]",
    }.get(fiscal_period, "")
    title = (
        f"[bold cyan]{corp_name}[/bold cyan] ({stock_code or '비상장'})"
        f" — {stmt_label} K-{'IFRS' if curr.get('is_ifrs', True) else 'GAAP'}"
        f"{period_mode_label}"
    )
    console.print(Panel(title, box=box.DOUBLE))

    # ── data_quality 경고 ────────────────────────────────────────────
    dq_warnings = []
    for sf in sf_list:
        dq = sf.get("data_quality", 1)
        fy = sf.get("fiscal_year", "?")
        fp = sf.get("fiscal_period", "FY")
        if dq >= 3:
            dq_warnings.append(f"[bold red]{fy} {fp}: 데이터 오류 (DQ=3) — 회계 항등식 불일치 또는 이상값[/bold red]")
        elif dq >= 2:
            dq_warnings.append(f"[yellow]{fy} {fp}: 데이터 경고 (DQ=2) — 검증 필요[/yellow]")
    if dq_warnings:
        console.print(Panel(
            "\n".join(dq_warnings),
            title="[bold yellow]Data Quality 경고[/bold yellow]",
            border_style="yellow",
            expand=False,
        ))

    # ── 기간 헤더 ────────────────────────────────────────────────────
    # 분기/반기 모드: "2024 Q1", "2024 H1" 등 / 연간 모드: "2024"
    if is_multi_period:
        period_labels = [_period_label(sf) for sf in sf_list]
        # YTD 안내
        if fiscal_period == "ALL":
            console.print("[dim]  ※ 분기/반기 수치는 연초 누적(YTD) 기준[/dim]")
    else:
        period_labels = [str(sf["fiscal_year"]) for sf in sf_list]

    # ── 손익계산서 테이블 ────────────────────────────────────────────
    _print_is_table(sf_list, period_labels, ratios, show_yoy=not is_multi_period)

    # ── 재무상태표 테이블 ────────────────────────────────────────────
    _print_bs_table(sf_list, period_labels, ratios)

    # ── 현금흐름 테이블 ──────────────────────────────────────────────
    _print_cf_table(sf_list, period_labels, ratios)

    # ── 분기/반기 모드: 여기서 종료 ─────────────────────────────────
    if is_multi_period:
        console.print("[dim]  ※ 성장성/밸류에이션/DuPont/버핏 지표는 연간(FY) 모드에서 확인하세요[/dim]")
        return

    # ── 성장성 & 효율성 테이블 (연간 모드만) ──────────────────────────
    _print_growth_table(sf_list, ratios)

    # ── 밸류에이션 테이블 ────────────────────────────────────────────
    _print_valuation_table(mults, curr, ratios)

    # ── DuPont 분해 ──────────────────────────────────────────────────
    _print_dupont_table(sf_list, ratios)

    # ── 버핏 관점 지표 ───────────────────────────────────────────────
    _print_buffett_table(buffett)


def _print_is_table(sf_list: list, years: list, ratios, show_yoy: bool = True) -> None:
    """손익계산서 테이블.

    Args:
        show_yoy: True=연간모드(YoY 열 표시) / False=분기모드(YoY 생략)
    """
    title_suffix = "" if show_yoy else " [YTD]"
    table = Table(title=f"손익계산서 (억원){title_suffix}", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("항목", style="cyan", width=22)

    # 분기모드에서 컬럼 폭 조정 (기간 레이블이 더 길다)
    col_width = 10 if show_yoy else 11
    for y in years:
        table.add_column(y, justify="right", width=col_width)

    if show_yoy:
        table.add_column("YoY", justify="right", width=8)

    def _row(label: str, key: str):
        vals = [sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None) for sf in sf_list]
        cells = [_fmt_amount(v) for v in vals]
        if show_yoy:
            yoy = ""
            if len(vals) >= 2 and vals[0] is not None and vals[1] is not None and vals[1] != 0:
                yoy_val = (vals[0] - vals[1]) / abs(vals[1])
                yoy = _fmt_pct(yoy_val)
            table.add_row(label, *cells, yoy)
        else:
            table.add_row(label, *cells)

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

    _row("매출액",          "revenue")
    _row("매출원가",        "cogs")
    _row("매출총이익",      "gross_profit")
    _row("판관비",          "sga")
    _row("영업이익",        "operating_income")
    _row("EBITDA",          "ebitda")
    _row("순이익",          "net_income")
    _row("지배주주 순이익", "controlling_ni")

    # 마진율
    table.add_section()

    def _margin_row(label, key):
        cells = _margin_cells(key)
        if show_yoy:
            table.add_row(label, *cells, "")
        else:
            table.add_row(label, *cells)

    _margin_row("매출총이익률", "gross_profit")
    _margin_row("영업이익률",   "operating_income")
    _margin_row("EBITDA마진",   "ebitda")
    _margin_row("순이익률",     "net_income")

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


def _print_growth_table(sf_list: list, ratios) -> None:
    """성장성 & 수익성 효율 테이블."""
    from analyzer.ratio_engine import _cagr, _safe_div

    table = Table(title="성장성 & 효율성", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("지표", style="cyan", width=22)
    table.add_column("당기", justify="right", width=10)
    table.add_column("3년 CAGR", justify="right", width=10)
    table.add_column("5년 CAGR", justify="right", width=10)

    def _get(sf, key):
        return sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None)

    def _cagr_cells(key):
        curr_val = _get(sf_list[0], key)
        val_3 = _get(sf_list[3], key) if len(sf_list) > 3 else None
        val_5 = _get(sf_list[5], key) if len(sf_list) > 5 else None
        c3 = _cagr(val_3, curr_val, 3) if val_3 and curr_val and val_3 > 0 else None
        c5 = _cagr(val_5, curr_val, 5) if val_5 and curr_val and val_5 > 0 else None
        return c3, c5

    def _add_growth(label, key):
        curr_val = _get(sf_list[0], key)
        prev_val = _get(sf_list[1], key) if len(sf_list) > 1 else None
        yoy = None
        if curr_val and prev_val and prev_val != 0:
            yoy = (curr_val - prev_val) / abs(prev_val)
        c3, c5 = _cagr_cells(key)
        table.add_row(
            label,
            _fmt_pct(yoy) if yoy is not None else "—",
            _fmt_pct(c3, sign=False) if c3 is not None else "—",
            _fmt_pct(c5, sign=False) if c5 is not None else "—",
        )

    _add_growth("매출 성장률", "revenue")
    _add_growth("영업이익 성장률", "operating_income")
    _add_growth("순이익 성장률", "net_income")
    _add_growth("총자산 성장률", "total_assets")

    # 수익성 지표 (단일 연도)
    table.add_section()

    def _add_ratio(label, value):
        table.add_row(label, _fmt_pct(value, sign=False) if value is not None else "—", "—", "—")

    _add_ratio("ROE",  ratios.roe)
    _add_ratio("ROA",  ratios.roa)
    _add_ratio("ROIC", ratios.roic)

    # R&D 비중
    sf0 = sf_list[0]
    rd = _get(sf0, "rd_expense")
    rev = _get(sf0, "revenue")
    rd_ratio = _safe_div(rd, rev) if rd and rev else None
    _add_ratio("R&D/매출", rd_ratio)

    # FCF 마진
    fcf = _get(sf0, "fcf")
    fcf_margin = _safe_div(fcf, rev) if fcf is not None and rev else None
    _add_ratio("FCF 마진", fcf_margin)

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


def _print_dupont_table(sf_list: list, ratios) -> None:
    """DuPont 3요소 분해 테이블 (ROE = 순이익률 × 자산회전율 × 재무레버리지)."""
    from analyzer.ratio_engine import compute_ratios

    table = Table(title="DuPont 분해 (ROE)", box=box.SIMPLE_HEAVY, title_style="bold")
    table.add_column("지표", style="cyan", width=22)
    for i, sf in enumerate(sf_list):
        fy = sf.get("fiscal_year") if isinstance(sf, dict) else getattr(sf, "fiscal_year", "")
        table.add_column(str(fy), justify="right", width=10)

    def _get(sf, key):
        return sf.get(key) if isinstance(sf, dict) else getattr(sf, key, None)

    rows = {
        "ROE": [],
        "순이익률": [],
        "자산회전율": [],
        "재무레버리지": [],
    }

    for sf in sf_list:
        r = compute_ratios(sf)
        ni  = _get(sf, "net_income")
        rev = _get(sf, "revenue")
        ta  = _get(sf, "total_assets")
        eq  = _get(sf, "total_equity")

        from analyzer.ratio_engine import _safe_div
        net_margin    = _safe_div(ni, rev)
        asset_turnover = _safe_div(rev, ta)
        leverage      = _safe_div(ta, eq)
        roe           = r.roe

        rows["ROE"].append(_fmt_pct(roe, sign=False) if roe is not None else "—")
        rows["순이익률"].append(_fmt_pct(net_margin, sign=False) if net_margin is not None else "—")
        rows["자산회전율"].append(f"{asset_turnover:.2f}x" if asset_turnover is not None else "—")
        rows["재무레버리지"].append(f"{leverage:.2f}x" if leverage is not None else "—")

    for label, cells in rows.items():
        style = "bold" if label == "ROE" else ""
        table.add_row(f"[{style}]{label}[/{style}]" if style else label, *cells)
        if label == "ROE":
            table.add_section()

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
