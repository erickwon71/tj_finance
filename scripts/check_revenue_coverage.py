"""
Revenue coverage verification tool
===================================
Outputs quarterly revenue table for all companies to a text file.

Usage:
    python3 scripts/check_revenue_coverage.py [--output PATH] [--since YEAR] [--market MARKET]

Output format:
    - Per-company block: fiscal_year rows × Q1/H1/Q3/FY columns (unit: 억원)
    - Missing data shown as "----"
    - Summary statistics at end of file

Statement priority: CFS (consolidated) > OFS (separate)
"""
import argparse
import os
import sys
from datetime import datetime

import psycopg2

# ── Config ──────────────────────────────────────────────────────────────────
DB_DSN    = "dbname=tj_finance user=taejin"
UNIT      = 100_000_000   # 억원
UNIT_LABEL = "억원"
PERIODS    = ["Q1", "H1", "Q3", "FY"]
COL_WIDTH  = 12   # width per period column


# ── DB helpers ───────────────────────────────────────────────────────────────

def fetch_data(since_year: int, market) -> list[dict]:
    """
    Returns rows: corp_code, corp_name, market, statement_type,
                  fiscal_year, fiscal_period, revenue
    Priority: CFS > OFS per (corp_code, fiscal_year, fiscal_period).
    """
    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()

    market_filter = ""
    params: list = [since_year]
    if market:
        market_filter = "AND c.market = %s"
        params.append(market.upper())

    # CFS 우선 — DISTINCT ON으로 중복 제거
    cur.execute(f"""
        SELECT
            c.corp_code,
            c.corp_name,
            COALESCE(c.market, '?') AS market,
            sf.statement_type,
            sf.fiscal_year,
            sf.fiscal_period,
            sf.revenue
        FROM corporations c
        JOIN (
            SELECT DISTINCT ON (corp_code, fiscal_year, fiscal_period)
                corp_code, statement_type, fiscal_year, fiscal_period, revenue
            FROM standard_financials
            WHERE fiscal_year >= %s
            ORDER BY corp_code, fiscal_year, fiscal_period,
                     CASE statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
        ) sf ON sf.corp_code = c.corp_code
        WHERE c.is_active = TRUE
        {market_filter}
        ORDER BY c.corp_name, c.corp_code, sf.fiscal_year, sf.fiscal_period
    """, params)

    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_active_corps(market) -> list[tuple]:
    """Returns (corp_code, corp_name, market) for all active corporations."""
    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()
    market_filter = "AND market = %s" if market else ""
    params = [market.upper()] if market else []
    cur.execute(f"""
        SELECT corp_code, corp_name, COALESCE(market,'?')
        FROM corporations
        WHERE is_active = TRUE
        {market_filter}
        ORDER BY corp_name
    """, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_downloaded_periods(since_year: int, market) -> set:
    """
    Returns set of (corp_code, fiscal_year, fiscal_period) where an is_final
    filing has a completed download task. Used to distinguish no-download (----)
    from downloaded-but-unparsed ((no-parse)).
    """
    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()
    market_filter = ""
    params = [since_year]
    if market:
        market_filter = "AND c.market = %s"
        params.append(market.upper())
    cur.execute(f"""
        SELECT DISTINCT f.corp_code, f.fiscal_year, f.fiscal_period
        FROM filings f
        JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        JOIN corporations c ON c.corp_code = f.corp_code
        WHERE f.is_final = TRUE
          AND dt.status = 'completed'
          AND f.fiscal_year >= %s
          {market_filter}
    """, params)
    result = {(r[0], r[1], r[2]) for r in cur.fetchall()}
    conn.close()
    return result


# ── Formatting helpers ───────────────────────────────────────────────────────

def fmt_revenue(val, downloaded: bool = True, future: bool = False) -> str:
    """Format revenue in 억원, right-aligned in COL_WIDTH."""
    if val is None:
        if future:
            return "····".rjust(COL_WIDTH)
        if downloaded:
            return "(no-parse)".rjust(COL_WIDTH)
        return "----".rjust(COL_WIDTH)
    awk = val / UNIT
    if awk >= 1_000_000:
        return f"{awk:,.0f}".rjust(COL_WIDTH)
    elif awk >= 1_000:
        return f"{awk:,.0f}".rjust(COL_WIDTH)
    elif awk >= 1:
        return f"{awk:,.1f}".rjust(COL_WIDTH)
    else:
        return f"{awk:.2f}".rjust(COL_WIDTH)


def period_header() -> str:
    sep = "  "
    return sep.join(p.center(COL_WIDTH) for p in PERIODS)


def divider(char: str = "-", extra: int = 0) -> str:
    base = 6 + 2 + len(period_header())  # year col + spacing + period cols
    return char * (base + extra)


# ── Main output builder ──────────────────────────────────────────────────────

def build_output(rows: list[dict], all_corps: list[tuple], since_year: int,
                 downloaded_periods: set = None) -> list[str]:
    lines: list[str] = []
    current_year = datetime.now().year

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append("=" * 100)
    lines.append(f"  TJ Finance — 분기별 매출액 커버리지 검증")
    lines.append(f"  생성일시 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  기준연도 : {since_year}년 이후")
    lines.append(f"  금액단위 : {UNIT_LABEL}")
    lines.append(f"  FS 우선순위: 연결재무제표(CFS) > 별도재무제표(OFS)")
    lines.append(f"  ※ '{current_year}년' 미도래 분기는 공백 집계에서 제외")
    lines.append(f"  셀 범례: 숫자=매출액(억원)  ····=미도래  ----=미다운로드  (no-parse)=다운로드됐으나 파싱실패")
    lines.append("=" * 100)
    lines.append("")

    # ── Index rows by corp ───────────────────────────────────────────────────
    from collections import defaultdict
    # { corp_code: { (fiscal_year, fiscal_period): row } }
    corp_data: dict[str, dict] = defaultdict(dict)
    corp_meta: dict[str, dict] = {}

    for r in rows:
        key = (r["fiscal_year"], r["fiscal_period"])
        corp_data[r["corp_code"]][key] = r
        corp_meta[r["corp_code"]] = {
            "corp_name":      r["corp_name"],
            "market":         r["market"],
            "statement_type": r["statement_type"],
        }

    # ── Per-company blocks ───────────────────────────────────────────────────
    total_corps    = len(all_corps)
    corps_with_sf  = len(corp_data)
    corps_no_sf    = total_corps - corps_with_sf

    missing_any_q : list[str] = []   # companies with at least one missing quarter
    no_data_corps : list[str] = []   # companies with no standard_financials at all

    for corp_code, corp_name, market in all_corps:
        if corp_code not in corp_data:
            no_data_corps.append(f"  {corp_code}  {corp_name:30s}  [{market}]")
            continue

        meta  = corp_meta[corp_code]
        cdata = corp_data[corp_code]

        years    = sorted({fy for (fy, _) in cdata})
        st_label = "CFS" if meta["statement_type"] == "consolidated" else "OFS"

        lines.append(f"{'─'*100}")
        lines.append(
            f"  {corp_code}  {corp_name}  [{market}]  {st_label}"
            f"  ({years[0]}~{years[-1]})"
        )
        lines.append(f"  {'연도':>6}  {period_header()}")
        lines.append(f"  {'':->6}  {divider('-', extra=0)}")

        corp_historical_missing = False
        for yr in years:
            revenue_vals = []
            for period in PERIODS:
                key = (yr, period)
                is_future = (yr >= current_year)
                if key in cdata:
                    rev = cdata[key]["revenue"]
                    is_dl = (downloaded_periods is None or
                             (corp_code, yr, period) in downloaded_periods)
                    revenue_vals.append(fmt_revenue(rev, downloaded=is_dl, future=False))
                    if rev is None and yr < current_year:
                        corp_historical_missing = True
                else:
                    if is_future:
                        revenue_vals.append("····".rjust(COL_WIDTH))
                    else:
                        is_dl = (downloaded_periods is not None and
                                 (corp_code, yr, period) in downloaded_periods)
                        revenue_vals.append(fmt_revenue(None, downloaded=is_dl, future=False))
                        corp_historical_missing = True

            row_str = "  ".join(revenue_vals)
            lines.append(f"  {yr:>6}  {row_str}")

        lines.append("")

        if corp_historical_missing:
            missing_any_q.append(f"  {corp_code}  {corp_name:30s}  [{market}]  {st_label}")

    # ── Summary ─────────────────────────────────────────────────────────────
    lines.append("=" * 100)
    lines.append("  커버리지 요약")
    lines.append("=" * 100)
    lines.append(f"  활성 기업 수         : {total_corps:,}")
    lines.append(f"  SF 데이터 있음       : {corps_with_sf:,}")
    lines.append(f"  SF 데이터 없음       : {corps_no_sf:,}")
    lines.append(f"  과거 분기 공백 있는 기업 : {len(missing_any_q):,}  (현재연도 미도래 제외)")
    lines.append(f"  ※ ---- = 미다운로드,  (no-parse) = 다운로드됐으나 매출액 파싱 실패")
    lines.append("")

    if no_data_corps:
        lines.append(f"  ── SF 데이터 없는 기업 ({len(no_data_corps)}개) ──")
        lines.extend(no_data_corps[:200])
        if len(no_data_corps) > 200:
            lines.append(f"  ... 외 {len(no_data_corps)-200}개 (전체 목록은 DB 조회 필요)")
        lines.append("")

    if missing_any_q:
        lines.append(f"  ── 과거 분기 공백 있는 기업 ({len(missing_any_q)}개) — ---- or (no-parse) 포함 기업 ──")
        lines.extend(missing_any_q[:200])
        if len(missing_any_q) > 200:
            lines.append(f"  ... 외 {len(missing_any_q)-200}개")
        lines.append("")

    lines.append("=" * 100)
    lines.append(f"  총 {len(rows):,}개 레코드 출력 완료")
    lines.append("=" * 100)

    return lines


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="분기별 매출액 커버리지 검증 도구")
    parser.add_argument(
        "--output", "-o",
        default="revenue_coverage.txt",
        help="출력 파일 경로 (기본: revenue_coverage.txt)",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=2000,
        help="검증 시작 연도 (기본: 2000, 수집 시작 연도)",
    )
    parser.add_argument(
        "--market",
        choices=["KOSPI", "KOSDAQ", "KONEX"],
        default=None,
        help="시장 필터 (기본: 전체)",
    )
    args = parser.parse_args()

    print(f"[1/3] DB 조회 중... (since={args.since}, market={args.market or '전체'})")
    rows               = fetch_data(args.since, args.market)
    all_corps          = fetch_active_corps(args.market)
    downloaded_periods = fetch_downloaded_periods(args.since, args.market)
    print(f"      → 레코드 {len(rows):,}건 / 활성기업 {len(all_corps):,}개"
          f" / 다운로드완료기간 {len(downloaded_periods):,}개")

    print("[2/3] 출력 구성 중...")
    lines = build_output(rows, all_corps, args.since, downloaded_periods)

    out_path = args.output
    print(f"[3/3] 파일 저장: {out_path}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    size_kb = os.path.getsize(out_path) / 1024
    print(f"완료: {out_path} ({size_kb:,.0f} KB, {len(lines):,}줄)")


if __name__ == "__main__":
    main()
