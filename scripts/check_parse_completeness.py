"""
Parse Completeness Verification
=================================
다운로드 완료된 파일 중 파싱 미완료(parse_status=NULL/failed/partial)이거나
핵심 재무 항목이 standard_financials에 없는 기간을 기업별로 집계한다.

핵심 항목 (모두 FY 기준, CFS 우선 → OFS 폴백):
  revenue, operating_income, net_income,
  total_assets, total_liabilities, total_equity,
  cfo, cfi, cff

출력:
  - parse_completeness.txt              : 전체 요약
  - logs/coverage/{code}_{name}.missing_parse.log : 기업별 최신 로그 (덮어쓰기)
  - logs/coverage/_INDEX_parse.txt      : 갭 기업 인덱스

단위: 억원 (1억 = 100,000,000원)

사용법:
    python3 scripts/check_parse_completeness.py [옵션]

옵션:
    --market  KOSPI | KOSDAQ (기본: 전체)
    --corp    특정 기업 corp_code
    --since   기준 fiscal_year (기본: 2015)
    --output  summary 파일 (기본: parse_completeness.txt)
    --log-dir 기업별 로그 디렉터리 (기본: logs/coverage)
    --no-logs 기업별 로그 미생성
"""
import argparse
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"
UNIT = 100_000_000  # 억원

CORE_ITEMS = [
    ("revenue",           "매출액"),
    ("operating_income",  "영업이익"),
    ("net_income",        "당기순이익"),
    ("total_assets",      "총자산"),
    ("total_liabilities", "총부채"),
    ("total_equity",      "총자본"),
    ("cfo",               "영업CF"),
    ("cfi",               "투자CF"),
    ("cff",               "재무CF"),
]
PERIODS = ["Q1", "H1", "Q3", "FY"]


# ── DB 조회 ──────────────────────────────────────────────────────────────────

def fetch_corps(market, corp_code) -> list[dict]:
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["is_active = TRUE"]
    params = []
    if market:
        clauses.append("market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    cur.execute(f"""
        SELECT corp_code, corp_name, COALESCE(market,'?') AS market
        FROM corporations WHERE {where} ORDER BY corp_code
    """, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_parse_status(since_year: int, market, corp_code) -> dict:
    """
    반환: {corp_code: {(fy, period): 'ok'|'failed'|'partial'|'null'|'no_dl'}}
    다운로드 완료된 건 중 파싱 현황 (is_final 우선)
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["c.is_active = TRUE", "f.report_type IS NOT NULL",
               "f.fiscal_year >= %s", "f.is_final = TRUE",
               "dt.status = 'completed'"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("c.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    cur.execute(f"""
        SELECT f.corp_code, f.fiscal_year, f.fiscal_period,
               COALESCE(dt.parse_status, 'null') AS pstatus
        FROM corporations c
        JOIN filings f ON f.corp_code = c.corp_code
        JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        WHERE {where}
    """, params)
    result: dict[str, dict] = defaultdict(dict)
    for corp_c, fy, fp, pstatus in cur.fetchall():
        if fp not in PERIODS:
            continue
        key = (fy, fp)
        existing = result[corp_c].get(key)
        # success trumps all
        if pstatus == "success":
            result[corp_c][key] = "ok"
        elif existing != "ok":
            result[corp_c][key] = pstatus
    conn.close()
    return dict(result)


def fetch_sf_items(since_year: int, market, corp_code) -> dict:
    """
    반환: {corp_code: {(fy, period, item): value_won}}
    CFS 우선 (DISTINCT ON 처리)
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    item_cols = ", ".join(f"sf.{item}" for item, _ in CORE_ITEMS)
    clauses = ["c.is_active = TRUE", "sf.fiscal_year >= %s"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("sf.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)

    cur.execute(f"""
        SELECT
            sf.corp_code, sf.fiscal_year, sf.fiscal_period,
            {item_cols}
        FROM (
            SELECT DISTINCT ON (corp_code, fiscal_year, fiscal_period)
                corp_code, fiscal_year, fiscal_period, statement_type,
                {item_cols.replace('sf.', '')}
            FROM standard_financials
            WHERE fiscal_year >= %s
            ORDER BY corp_code, fiscal_year, fiscal_period,
                     CASE statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
        ) sf
        JOIN corporations c ON c.corp_code = sf.corp_code
        WHERE {where}
    """, [since_year] + params)

    result: dict[str, dict] = defaultdict(dict)
    col_names = [d[0] for d in cur.description]
    item_names = [item for item, _ in CORE_ITEMS]
    for row in cur.fetchall():
        corp_c, fy, fp = row[0], row[1], row[2]
        if fp not in PERIODS:
            continue
        for i, iname in enumerate(item_names):
            result[corp_c][(fy, fp, iname)] = row[3 + i]
    conn.close()
    return dict(result)


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────

def _fmt(val) -> str:
    if val is None:
        return "----"
    awk = val / UNIT
    if abs(awk) >= 1000:
        return f"{awk:,.0f}"
    elif abs(awk) >= 1:
        return f"{awk:,.1f}"
    else:
        return f"{awk:.2f}"


def _safe_name(corp_name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', corp_name)


# ── 기업별 로그 ───────────────────────────────────────────────────────────────

def write_corp_parse_log(
    corp: dict,
    parse_status: dict,   # {(fy, fp): status}
    sf_items: dict,       # {(fy, fp, item): value}
    years: list[int],
    log_dir: Path,
    today: date,
) -> bool:
    """갭이 있으면 로그 기록 후 True, 없으면 False."""
    code = corp["corp_code"]
    name = corp["corp_name"]
    safe = _safe_name(name)
    log_path = log_dir / f"{code}_{safe}.missing_parse.log"

    # 갭: 파싱 미완료 또는 핵심 FY 항목 결측
    parse_gaps = [(fy, fp) for (fy, fp), st in parse_status.items()
                  if st not in ("ok", "success") and fp == "FY"]
    item_gaps = [(fy, fp, item)
                 for fy in years
                 for fp in PERIODS
                 for item, _ in CORE_ITEMS
                 if sf_items.get((fy, fp, item)) is None
                 and parse_status.get((fy, fp)) == "ok"]

    if not parse_gaps and not item_gaps:
        if log_path.exists():
            log_path.unlink()
        return False

    lines = []
    lines.append(f"# {code}  {name}  [{corp['market']}]")
    lines.append(f"# 생성: {today.isoformat()}  (최신본 덮어쓰기)")
    lines.append("")

    if parse_gaps:
        lines.append(f"## 파싱 미완료 FY 기간 ({len(parse_gaps)}건)")
        lines.append(f"  {'연도':>6}  {'상태':<10}  권장 조치")
        lines.append(f"  {'──────':>6}  {'──────────':<10}  ──────────────────")
        for fy, fp in sorted(parse_gaps):
            st = parse_status.get((fy, fp), "?")
            action = f"python run.py parse-reset  → parse"
            lines.append(f"  {fy:>6}  {st:<10}  {action}")
        lines.append("")

    if item_gaps:
        lines.append(f"## 핵심 항목 결측 (파싱 완료 후에도 SF 미집계, {len(item_gaps)}건)")
        lines.append(f"  {'연도':>6}  {'기간':<4}  {'항목':<16}  권장 조치")
        lines.append(f"  {'──────':>6}  {'────':<4}  {'────────────────':<16}  ──────────")
        for fy, fp, item in sorted(item_gaps):
            label = next((l for i, l in CORE_ITEMS if i == item), item)
            lines.append(f"  {fy:>6}  {fp:<4}  {label:<16}  python run.py aggregate --corp {code}")
        lines.append("")

    # 핵심 항목 요약표 (FY만, 억원)
    fy_years = sorted({fy for (fy, fp) in parse_status if fp == "FY"}, reverse=True)[:8]
    if fy_years:
        lines.append("## 핵심 항목 현황 (FY, 억원)")
        hdr = f"  {'연도':>6}  " + "  ".join(f"{l:>8}" for _, l in CORE_ITEMS)
        lines.append(hdr)
        lines.append("  " + "─" * (len(hdr) - 2))
        for fy in fy_years:
            vals = [sf_items.get((fy, "FY", item)) for item, _ in CORE_ITEMS]
            row = f"  {fy:>6}  " + "  ".join(f"{_fmt(v):>8}" for v in vals)
            lines.append(row)
        lines.append("")

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return True


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="파싱 완전성 + 핵심 항목 결측 검증")
    ap.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    ap.add_argument("--corp", default=None, metavar="CORP_CODE")
    ap.add_argument("--since", type=int, default=2015)
    ap.add_argument("--output", default="parse_completeness.txt")
    ap.add_argument("--log-dir", default="logs/coverage")
    ap.add_argument("--no-logs", action="store_true")
    args = ap.parse_args()

    today = date.today()
    log_dir = Path(args.log_dir)
    if not args.no_logs:
        log_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] 기업 목록 조회...")
    corps = fetch_corps(args.market, args.corp)
    print(f"      → {len(corps):,}개 기업")

    print("[2/4] 파싱 현황 조회...")
    parse_map = fetch_parse_status(args.since, args.market, args.corp)

    print("[3/4] 핵심 항목 집계 조회...")
    sf_map = fetch_sf_items(args.since, args.market, args.corp)

    print("[4/4] 분석 및 로그 생성...")

    gap_corps = []
    total_parse_ok = total_parse_gap = total_item_gap = 0

    for corp in corps:
        code = corp["corp_code"]
        corp_ps = parse_map.get(code, {})
        corp_sf = sf_map.get(code, {})

        years = sorted({fy for (fy, _) in corp_ps}, reverse=True)

        p_ok  = sum(1 for st in corp_ps.values() if st == "ok")
        p_gap = sum(1 for st in corp_ps.values() if st not in ("ok",))
        i_gap = sum(
            1
            for fy in years
            for fp in PERIODS
            for item, _ in CORE_ITEMS
            if corp_sf.get((fy, fp, item)) is None and corp_ps.get((fy, fp)) == "ok"
        )

        total_parse_ok  += p_ok
        total_parse_gap += p_gap
        total_item_gap  += i_gap

        has_gap = (p_gap > 0) or (i_gap > 0)
        if has_gap:
            gap_corps.append(corp)

        if not args.no_logs:
            write_corp_parse_log(corp, corp_ps, corp_sf, years, log_dir, today)

    # 요약 출력
    out = []
    out.append("=" * 90)
    out.append("  TJ Finance — Parse Completeness Verification")
    out.append(f"  Generated : {today.isoformat()}")
    out.append(f"  Market    : {args.market or '전체'}")
    out.append(f"  Since     : {args.since}")
    out.append("=" * 90)
    out.append("")
    out.append(f"  대상 기업          : {len(corps):,}")
    out.append(f"  파싱 완료 기간     : {total_parse_ok:,}")
    out.append(f"  파싱 미완료 기간   : {total_parse_gap:,}")
    out.append(f"  핵심 항목 결측     : {total_item_gap:,}  (파싱 완료 후에도 SF 미집계)")
    out.append(f"  갭 있는 기업       : {len(gap_corps):,} / {len(corps):,}")
    out.append("")

    if gap_corps:
        out.append(f"  ── 갭 있는 기업 ({len(gap_corps)}개) ──")
        for corp in gap_corps[:300]:
            out.append(f"    {corp['corp_code']}  {corp['corp_name']:30s}  [{corp['market']}]")
        if len(gap_corps) > 300:
            out.append(f"    ... 외 {len(gap_corps)-300}개 (로그 파일 참조)")
        out.append("")

    out.append("  권장 조치:")
    out.append("    파싱 미완료 → python run.py parse-reset  →  python run.py parse")
    out.append("    항목 결측   → python run.py aggregate --since <since>")
    out.append("")

    if not args.no_logs:
        index_path = log_dir / "_INDEX_parse.txt"
        idx = [f"# 파싱 갭 인덱스 — {today.isoformat()}", f"# 갭 기업: {len(gap_corps)}", ""]
        for corp in gap_corps:
            idx.append(f"  {corp['corp_code']}  {corp['corp_name']:30s}  [{corp['market']}]")
        index_path.write_text("\n".join(idx), encoding="utf-8")
        out.append(f"  기업별 로그: {log_dir}/{{corp_code}}_{{name}}.missing_parse.log")
        out.append(f"  인덱스: {index_path}")

    out.append("=" * 90)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print(f"완료: {args.output}")
    print(f"  파싱완료={total_parse_ok:,}  미완료={total_parse_gap:,}  항목결측={total_item_gap:,}")
    print(f"  갭 기업: {len(gap_corps):,}개")


if __name__ == "__main__":
    main()
