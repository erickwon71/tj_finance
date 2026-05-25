"""
멀티 기업 비교 엔진

사용 예:
    python run.py compare --corps 00126380,00164779,00164742
"""
from __future__ import annotations

from typing import Optional
from loguru import logger


def _load_company(corp_code: str, statement_type: str = "consolidated") -> Optional[dict]:
    """단일 기업의 최신 FY 2개년 + 시가총액 로드."""
    from analyzer.ratio_engine import load_standard_financials
    from collector.db import get_session
    from sqlalchemy import text

    sfs = load_standard_financials(corp_code, statement_type=statement_type, fiscal_period="FY", years=2)
    if not sfs:
        # fallback: separate
        sfs = load_standard_financials(corp_code, statement_type="separate", fiscal_period="FY", years=2)
        if sfs:
            statement_type = "separate"

    if not sfs:
        return None

    # 기업 정보 + 최신 시가총액
    with get_session() as session:
        info = session.execute(text("""
            SELECT c.corp_name, c.stock_code, c.market,
                   sp.close_price, sp.market_cap
            FROM corporations c
            LEFT JOIN LATERAL (
                SELECT close_price, market_cap
                FROM stock_prices
                WHERE stock_code = c.stock_code
                  AND market_cap IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            ) sp ON TRUE
            WHERE c.corp_code = :cc
        """), {"cc": corp_code}).fetchone()

    return {
        "corp_code":      corp_code,
        "corp_name":      info.corp_name if info else corp_code,
        "stock_code":     info.stock_code if info else None,
        "market":         info.market if info else None,
        "close_price":    info.close_price if info else None,
        "market_cap":     info.market_cap if info else None,
        "statement_type": statement_type,
        "curr":           sfs[0],
        "prev":           sfs[1] if len(sfs) > 1 else None,
    }


def compare(
    corp_codes: list[str],
    statement_type: str = "consolidated",
) -> list[dict]:
    """
    여러 기업의 핵심 지표를 계산해 비교 데이터 반환.

    Returns:
        각 기업의 지표 dict 리스트
    """
    from analyzer.ratio_engine import compute_ratios
    from analyzer.buffett_engine import compute_buffett

    results = []
    for cc in corp_codes:
        data = _load_company(cc, statement_type)
        if not data:
            logger.warning(f"데이터 없음: {cc}")
            continue

        curr    = data["curr"]
        prev    = data.get("prev")
        mktcap  = data.get("market_cap")
        ratios  = compute_ratios(curr, prev)

        # 밸류에이션
        ni      = curr.get("net_income") or 0
        eq      = curr.get("total_equity") or 0
        ebitda_raw = curr.get("ebitda")          # None → "—" 표시용
        ebitda  = ebitda_raw or 0                # 계산용 (0으로 폴백)
        net_dt  = curr.get("net_debt") or 0
        rev     = curr.get("revenue") or 0
        cfo     = curr.get("cfo") or 0
        divs    = curr.get("dividends_paid")

        def _div(a, b):
            return a / b if a and b and b != 0 else None

        ev = (mktcap or 0) + (net_dt or 0)

        # Piotroski
        piotroski = None
        try:
            sf_list = [curr] + ([prev] if prev else [])
            bm = compute_buffett(sf_list, mktcap)
            piotroski = bm.piotroski_f_score
        except Exception:
            pass

        # DPS / 배당수익률
        shares   = curr.get("shares_out")
        dps      = abs(divs) / shares if divs and shares else None
        div_yield = _div(dps, data.get("close_price")) if dps else None

        results.append({
            "corp_code":     cc,
            "corp_name":     data["corp_name"],
            "stock_code":    data["stock_code"],
            "market":        data["market"],
            "fiscal_year":   curr["fiscal_year"],
            "stmt_type":     data["statement_type"],
            # 규모
            "revenue":       rev,
            "op_income":     curr.get("operating_income"),
            "net_income":    ni,
            "total_assets":  curr.get("total_assets"),
            "total_equity":  eq,
            "net_debt":      net_dt,
            "market_cap":    mktcap,
            "ebitda":        ebitda_raw,   # None이면 "—" 표시
            "fcf":           curr.get("fcf"),
            "cfo":           cfo,
            # 수익성
            "gross_margin":  ratios.gross_margin,
            "op_margin":     ratios.op_margin,
            "net_margin":    ratios.net_margin,
            "ebitda_margin": ratios.ebitda_margin,
            "roe":           ratios.roe,
            "roa":           ratios.roa,
            "roic":          ratios.roic,
            # 밸류에이션
            "per":           _div(mktcap, ni)    if ni > 0 else None,
            "pbr":           _div(mktcap, eq)    if eq > 0 else None,
            "ev_ebitda":     _div(ev, ebitda)    if ebitda > 0 else None,
            "pcr":           _div(mktcap, cfo)   if cfo > 0 else None,
            "psr":           _div(mktcap, rev)   if rev > 0 else None,
            # 성장성
            "revenue_growth":   ratios.revenue_growth,
            "op_growth":        ratios.op_income_growth,
            "ni_growth":        ratios.net_income_growth,
            # 안정성
            "debt_ratio":       ratios.debt_ratio,
            "current_ratio":    ratios.current_ratio,
            "interest_coverage": ratios.interest_coverage,
            # 효율성
            "capex_to_rev":     ratios.capex_to_revenue,
            "fcf_to_rev":       ratios.fcf_to_revenue,
            "fcf_quality":      ratios.cfo_to_ni,
            # 배당
            "div_yield":        div_yield,
            # 복합
            "piotroski":        piotroski,
        })

    return results


# ── Rich 출력 ─────────────────────────────────────────────────────────────────

def print_compare_results(results: list[dict]) -> None:
    """기업 비교를 세로 항목 × 가로 기업 테이블로 출력."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    if not results:
        Console().print("[yellow]비교할 기업 데이터가 없습니다.[/yellow]")
        return

    console = Console(width=220)
    n = len(results)

    # ── 헬퍼 ────────────────────────────────────────────────────────
    def _won(v, unit=1e12):
        """원 단위 금액 → 조원 또는 억원"""
        if v is None: return "—"
        if unit == 1e12: return f"{v/1e12:.1f}조"
        return f"{v/1e8:.0f}억"

    def _pct(v):
        return f"{v*100:.1f}%" if v is not None else "—"
    def _pct_chg(v):
        return f"{v*100:+.1f}%" if v is not None else "—"
    def _x(v, d=1):
        return f"{v:.{d}f}x" if v is not None else "—"

    # best/worst 강조 (숫자만)
    def _best(vals, higher_better=True):
        """최고값 인덱스 반환 (None 제외)"""
        valid = [(i, v) for i, v in enumerate(vals) if v is not None]
        if not valid: return set()
        best_v = max(v for _, v in valid) if higher_better else min(v for _, v in valid)
        return {i for i, v in valid if abs(v - best_v) < 1e-12}

    def _row_vals(key):
        return [r.get(key) for r in results]

    def _color(val, best_set, idx, fmt_fn):
        s = fmt_fn(val)
        if idx in best_set:
            return f"[bold green]{s}[/bold green]"
        return s

    # ── 테이블 구성 ──────────────────────────────────────────────────
    names = [r["corp_name"][:14] for r in results]
    mkts  = [r.get("market", "?") for r in results]
    fys   = [str(r.get("fiscal_year", "?")) for r in results]
    stmts = [("연결" if r["stmt_type"] == "consolidated" else "별도") for r in results]

    tbl = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white",
        title=f"기업 비교 ({n}개사)",
    )

    tbl.add_column("항목", style="dim", width=18, no_wrap=True)
    for nm, mkt, fy, st in zip(names, mkts, fys, stmts):
        mkt_c = "green" if mkt == "KOSPI" else "cyan"
        tbl.add_column(
            f"[bold]{nm}[/bold]\n[{mkt_c}]{mkt}[/{mkt_c}] {fy} {st}",
            justify="right", width=14,
        )

    def _add_section(title):
        tbl.add_row(f"[bold yellow]{title}[/bold yellow]", *[""] * n)

    def _add_row(label, key, fmt_fn, higher_better=True):
        vals = _row_vals(key)
        best = _best(vals, higher_better)
        cells = [_color(v, best, i, fmt_fn) for i, v in enumerate(vals)]
        tbl.add_row(label, *cells)

    # ── 규모 ────────────────────────────────────────────────────────
    _add_section("▌ 규모")
    _add_row("시가총액",    "market_cap",   lambda v: _won(v))
    _add_row("매출액",      "revenue",      lambda v: _won(v))
    _add_row("영업이익",    "op_income",    lambda v: _won(v))
    _add_row("순이익",      "net_income",   lambda v: _won(v))
    _add_row("EBITDA",      "ebitda",       lambda v: _won(v))
    _add_row("FCF",         "fcf",          lambda v: _won(v))
    _add_row("총자산",      "total_assets", lambda v: _won(v))
    _add_row("순부채",      "net_debt",     lambda v: _won(v), higher_better=False)

    # ── 수익성 ──────────────────────────────────────────────────────
    _add_section("▌ 수익성")
    _add_row("매출총이익률", "gross_margin", _pct)
    _add_row("영업이익률",  "op_margin",    _pct)
    _add_row("순이익률",    "net_margin",   _pct)
    _add_row("EBITDA 마진", "ebitda_margin",_pct)
    _add_row("ROE",         "roe",          _pct)
    _add_row("ROA",         "roa",          _pct)
    _add_row("ROIC",        "roic",         _pct)

    # ── 밸류에이션 ───────────────────────────────────────────────────
    _add_section("▌ 밸류에이션")
    _add_row("PER",         "per",          lambda v: _x(v), higher_better=False)
    _add_row("PBR",         "pbr",          lambda v: _x(v), higher_better=False)
    _add_row("EV/EBITDA",   "ev_ebitda",    lambda v: _x(v), higher_better=False)
    _add_row("PCR",         "pcr",          lambda v: _x(v), higher_better=False)
    _add_row("PSR",         "psr",          lambda v: _x(v), higher_better=False)

    # ── 성장성 ──────────────────────────────────────────────────────
    _add_section("▌ 성장성 (YoY)")
    _add_row("매출 성장",   "revenue_growth", _pct_chg)
    _add_row("영업이익 성장","op_growth",     _pct_chg)
    _add_row("순이익 성장", "ni_growth",      _pct_chg)

    # ── 안정성 ──────────────────────────────────────────────────────
    _add_section("▌ 안정성")
    _add_row("부채비율",    "debt_ratio",     lambda v: _x(v), higher_better=False)
    _add_row("유동비율",    "current_ratio",  lambda v: _x(v))
    _add_row("이자보상배율","interest_coverage", lambda v: _x(v))

    # ── 효율성 ──────────────────────────────────────────────────────
    _add_section("▌ 효율성 & 배당")
    _add_row("CAPEX/매출",  "capex_to_rev",   _pct, higher_better=False)
    _add_row("FCF/매출",    "fcf_to_rev",     _pct)
    _add_row("FCF 품질",    "fcf_quality",    lambda v: _x(v))
    _add_row("배당수익률",  "div_yield",      _pct)

    # ── 복합 ────────────────────────────────────────────────────────
    _add_section("▌ 복합")
    def _ps_fmt(v):
        if v is None: return "—"
        c = "green" if v >= 7 else ("yellow" if v >= 5 else "red")
        return f"[{c}]{v}/9[/{c}]"
    vals = _row_vals("piotroski")
    best = _best(vals)
    cells = [_ps_fmt(v) for v in vals]  # 색상 이미 포함 — _color 미사용
    tbl.add_row("Piotroski F", *cells)

    console.print(tbl)
    console.print("[dim]굵은 녹색 = 해당 항목 최고값[/dim]\n")
