"""
스크리닝 엔진 — 재무 조건 기반 기업 필터링

사용 예:
    python run.py screen --roe ">15%" --per "<12" --market KOSPI
    python run.py screen --piotroski ">=7" --revenue-growth ">10%" --sort roe
    python run.py screen --debt-ratio "<1" --roic ">10%" --limit 20
"""
from __future__ import annotations

import re
from typing import Optional
from loguru import logger


# ── 조건 파싱 ─────────────────────────────────────────────────────────────────
# 지원 형식: ">15%"  ">=0.15"  "<12"  "<=1.5"  "=7"
_COND_RE = re.compile(r"^(>=|<=|>|<|=)\s*([\d.]+)(%?)$")

def _parse_condition(expr: str) -> tuple[str, float]:
    """
    ">15%"  → ("gt", 0.15)
    ">=7"   → ("gte", 7.0)
    "<12"   → ("lt", 12.0)
    "<=1.5" → ("lte", 1.5)
    "=5"    → ("eq", 5.0)
    """
    m = _COND_RE.match(expr.strip())
    if not m:
        raise ValueError(f"조건 형식 오류: '{expr}' (예: '>15%', '<12', '>=7')")
    op_sym, num_str, pct = m.groups()
    val = float(num_str)
    if pct == "%":
        val /= 100.0
    op_map = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "=": "eq"}
    return op_map[op_sym], val


def _check(value, op, threshold) -> bool:
    if value is None:
        return False
    if op == "gt":  return value > threshold
    if op == "gte": return value >= threshold
    if op == "lt":  return value < threshold
    if op == "lte": return value <= threshold
    if op == "eq":  return abs(value - threshold) < 1e-9
    return False


# ── 데이터 로드 ───────────────────────────────────────────────────────────────

def _load_screening_data(fiscal_year: Optional[int] = None) -> list[dict]:
    """
    전체 기업의 최신 FY 데이터(curr+prev 2개년) + 최신 시가총액을 한 번에 로드.

    반환: [{"corp_code", "corp_name", "stock_code", "market",
             "close_price", "market_cap", "curr": dict, "prev": dict}, ...]
    """
    from collector.db import get_session
    from sqlalchemy import text

    year_filter = f"AND sf.fiscal_year = {fiscal_year}" if fiscal_year else ""

    sql = f"""
        WITH ranked AS (
            SELECT
                sf.corp_code, sf.fiscal_year, sf.fiscal_period,
                sf.statement_type, sf.period_end, sf.data_quality,
                sf.total_assets, sf.current_assets, sf.cash,
                sf.receivables, sf.inventory, sf.ppe,
                sf.total_liabilities, sf.current_liabilities,
                sf.short_term_debt, sf.long_term_debt,
                sf.total_equity, sf.controlling_equity, sf.retained_earnings,
                sf.trade_payables,
                sf.revenue, sf.cogs, sf.gross_profit, sf.sga, sf.rd_expense,
                sf.operating_income, sf.interest_expense, sf.ebt,
                sf.tax_expense, sf.net_income, sf.controlling_ni,
                sf.cfo, sf.cfi, sf.cff, sf.capex, sf.dividends_paid,
                sf.depreciation, sf.amortization, sf.da_total,
                sf.ebitda, sf.fcf, sf.net_debt, sf.shares_out,
                c.corp_name, c.stock_code, c.market,
                sp.close_price, sp.market_cap,
                ROW_NUMBER() OVER (
                    PARTITION BY sf.corp_code
                    ORDER BY sf.fiscal_year DESC
                ) AS rn
            FROM standard_financials sf
            JOIN corporations c ON c.corp_code = sf.corp_code
            LEFT JOIN LATERAL (
                SELECT close_price, market_cap
                FROM stock_prices
                WHERE stock_code = c.stock_code
                  AND market_cap IS NOT NULL
                ORDER BY trade_date DESC
                LIMIT 1
            ) sp ON TRUE
            WHERE sf.fiscal_period    = 'FY'
              AND sf.statement_type   = 'consolidated'
              AND sf.data_quality     < 3
              AND c.stock_code        IS NOT NULL
              {year_filter}
        )
        SELECT * FROM ranked WHERE rn <= 2
        ORDER BY corp_code, rn
    """

    with get_session() as session:
        rows = session.execute(text(sql)).mappings().fetchall()

    # corp_code별로 curr/prev 분리
    companies: dict[str, dict] = {}
    for row in rows:
        cc = row["corp_code"]
        rn = row["rn"]
        if cc not in companies:
            companies[cc] = {
                "corp_code":   cc,
                "corp_name":   row["corp_name"],
                "stock_code":  row["stock_code"],
                "market":      row["market"],
                "close_price": row["close_price"],
                "market_cap":  row["market_cap"],
            }
        if rn == 1:
            companies[cc]["curr"] = dict(row)
        elif rn == 2:
            companies[cc]["prev"] = dict(row)

    # curr 없는 항목 제거
    return [v for v in companies.values() if "curr" in v]


# ── 스크리닝 실행 ─────────────────────────────────────────────────────────────

def screen(
    filters: Optional[dict] = None,
    market: Optional[str] = None,
    sort_by: str = "roe",
    sort_asc: bool = False,
    limit: int = 30,
    fiscal_year: Optional[int] = None,
    min_market_cap: Optional[float] = None,  # 최소 시총 (조)
) -> list[dict]:
    """
    재무 조건으로 기업 스크리닝.

    Args:
        filters:  {"roe": ">15%", "per": "<12", ...}  — 조건 문자열 또는 (op, val) 튜플
        market:   "KOSPI" / "KOSDAQ" / None
        sort_by:  정렬 기준 필드명
        sort_asc: True=오름차순, False=내림차순
        limit:    출력 최대 건 수
        fiscal_year: 특정 연도 고정 (None=최신)
        min_market_cap: 최소 시가총액 (조원)

    Returns:
        [{"corp_name", "market", "fiscal_year", "roe", "per", ...}, ...]
    """
    from analyzer.ratio_engine import compute_ratios
    from analyzer.buffett_engine import compute_buffett

    # 조건 파싱
    parsed_filters: dict[str, tuple[str, float]] = {}
    for key, expr in (filters or {}).items():
        if isinstance(expr, str):
            try:
                parsed_filters[key] = _parse_condition(expr)
            except ValueError as e:
                logger.error(str(e))
                return []
        else:
            parsed_filters[key] = expr  # 이미 튜플

    logger.info("스크리닝 데이터 로드 중...")
    companies = _load_screening_data(fiscal_year)
    logger.info(f"  로드: {len(companies)}개 기업")

    results = []

    for co in companies:
        # 시장 필터
        if market and co.get("market", "").upper() != market.upper():
            continue

        curr = co["curr"]
        prev = co.get("prev")

        # 시총 필터
        mktcap = co.get("market_cap")
        if min_market_cap and (not mktcap or mktcap < min_market_cap * 1e12):
            continue

        # 비율 계산
        ratios = compute_ratios(curr, prev)

        # 밸류에이션 멀티플 계산
        ni     = curr.get("net_income") or 0
        eq     = curr.get("total_equity") or 0
        ebitda = curr.get("ebitda") or 0
        cfo    = curr.get("cfo") or 0
        net_dt = curr.get("net_debt") or 0
        rev    = curr.get("revenue") or 0

        def _div(a, b):
            return a / b if a and b and b != 0 else None

        ev      = (mktcap or 0) + (net_dt or 0)
        per     = _div(mktcap, ni)     if ni > 0 else None
        pbr     = _div(mktcap, eq)     if eq > 0 else None
        ev_ebit = _div(ev, ebitda)     if ebitda > 0 else None
        pcr     = _div(mktcap, cfo)    if cfo > 0 else None
        psr     = _div(mktcap, rev)    if rev > 0 else None

        # Piotroski
        piotroski = None
        try:
            sf_list = [curr]
            if prev:
                sf_list.append(prev)
            bm = compute_buffett(sf_list, mktcap)
            piotroski = bm.piotroski_f_score
        except Exception:
            pass

        row = {
            "corp_code":       co["corp_code"],
            "corp_name":       co["corp_name"],
            "stock_code":      co["stock_code"],
            "market":          co["market"],
            "fiscal_year":     curr["fiscal_year"],
            "market_cap_jo":   mktcap / 1e12 if mktcap else None,  # 조원
            # 수익성
            "roe":             ratios.roe,
            "roa":             ratios.roa,
            "roic":            ratios.roic,
            "op_margin":       ratios.op_margin,
            "net_margin":      ratios.net_margin,
            "ebitda_margin":   ratios.ebitda_margin,
            # 밸류에이션
            "per":             per,
            "pbr":             pbr,
            "ev_ebitda":       ev_ebit,
            "pcr":             pcr,
            "psr":             psr,
            # 성장성
            "revenue_growth":  ratios.revenue_growth,
            "op_growth":       ratios.op_income_growth,
            "ni_growth":       ratios.net_income_growth,
            # 안정성
            "debt_ratio":      ratios.debt_ratio,
            "current_ratio":   ratios.current_ratio,
            "interest_coverage": ratios.interest_coverage,
            # 효율성
            "ccc":             ratios.ccc,
            # 이익품질
            "fcf_quality":     ratios.cfo_to_ni,
            "accrual_ratio":   ratios.accrual_ratio,
            # 복합
            "piotroski":       piotroski,
        }

        # 필터 적용
        passed = True
        for key, (op, threshold) in parsed_filters.items():
            val = row.get(key)
            if not _check(val, op, threshold):
                passed = False
                break
        if not passed:
            continue

        results.append(row)

    # 정렬
    def _sort_key(r):
        v = r.get(sort_by)
        if v is None:
            return (1, 0)
        return (0, v)

    results.sort(key=_sort_key, reverse=not sort_asc)
    return results[:limit]


# ── Rich 출력 ─────────────────────────────────────────────────────────────────

def print_screen_results(
    results: list[dict],
    filters: Optional[dict] = None,
    sort_by: str = "roe",
    market: Optional[str] = None,
) -> None:
    """스크리닝 결과를 Rich 테이블로 출력."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console(width=220)

    if not results:
        console.print("\n[yellow]조건에 맞는 기업이 없습니다.[/yellow]")
        return

    # 헤더 출력
    filter_str = "  ".join(
        f"[cyan]{k}[/cyan] {v}" for k, v in (filters or {}).items()
    )
    market_str = f"  [cyan]market[/cyan] {market}" if market else ""
    console.print(f"\n[bold]스크리닝 결과[/bold]  {filter_str}{market_str}  → [green]{len(results)}건[/green]\n")

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold white")

    def _pct(v):
        return f"{v*100:+.1f}%" if v is not None else "—"
    def _pct_pos(v):
        return f"{v*100:.1f}%" if v is not None else "—"
    def _x(v, d=1):
        return f"{v:.{d}f}x" if v is not None else "—"
    def _mktcap(v):
        return f"{v:.1f}조" if v is not None else "—"

    # 컬럼 정의
    tbl.add_column("기업명",     style="bold", min_width=14, no_wrap=True)
    tbl.add_column("시장",       min_width=6,  no_wrap=True)
    tbl.add_column("FY",         min_width=4,  no_wrap=True)
    tbl.add_column("시총",       min_width=7,  justify="right", no_wrap=True)
    tbl.add_column("ROE",        min_width=7,  justify="right", no_wrap=True)
    tbl.add_column("ROIC",       min_width=7,  justify="right", no_wrap=True)
    tbl.add_column("PER",        min_width=6,  justify="right", no_wrap=True)
    tbl.add_column("PBR",        min_width=6,  justify="right", no_wrap=True)
    tbl.add_column("EV/EBITDA",  min_width=9,  justify="right", no_wrap=True)
    tbl.add_column("영업이익률",  min_width=8,  justify="right", no_wrap=True)
    tbl.add_column("매출성장",    min_width=8,  justify="right", no_wrap=True)
    tbl.add_column("부채비율",    min_width=7,  justify="right", no_wrap=True)
    tbl.add_column("F-Score",    min_width=7,  justify="right", no_wrap=True)

    for r in results:
        mkt_color = "green" if r.get("market") == "KOSPI" else "cyan"
        ps = r.get("piotroski")
        ps_str = f"{ps}/9" if ps is not None else "—"
        ps_color = "green" if ps and ps >= 7 else ("yellow" if ps and ps >= 5 else "red")

        tbl.add_row(
            r["corp_name"][:14],
            f"[{mkt_color}]{r.get('market','?')}[/{mkt_color}]",
            str(r.get("fiscal_year", "?")),
            _mktcap(r.get("market_cap_jo")),
            _pct_pos(r.get("roe")),
            _pct_pos(r.get("roic")),
            _x(r.get("per")),
            _x(r.get("pbr")),
            _x(r.get("ev_ebitda")),
            _pct_pos(r.get("op_margin")),
            _pct(r.get("revenue_growth")),
            _x(r.get("debt_ratio")),
            f"[{ps_color}]{ps_str}[/{ps_color}]",
        )

    console.print(tbl)
    console.print(f"[dim]정렬 기준: {sort_by}  |  데이터 부족(*) 기업은 제외됨[/dim]\n")
