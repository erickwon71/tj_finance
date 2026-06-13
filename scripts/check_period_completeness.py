"""
Period Completeness Verification
=================================
상장(정보공개) 시점부터 현재까지 기대되는 분기/반기/사업보고서를 격자로 계산하고,
실제 수집 현황과 대조해 갭을 탐지한다.

기존 check_download_coverage.py 는 '등록된 공시'의 다운로드 여부만 확인.
이 스크립트는 '기대 기간' 대비 완전성을 확인한다.

셀 상태:
  OK      — is_final filing이 있고 download_task.status='completed'
  NODL    — is_final filing이 있으나 미다운로드/실패
  NOFIL   — filing 자체가 DB에 없음  → sync-filings --corp --force 권장
  FUTURE  — 제출 마감이 아직 도래하지 않은 기간

결산월(fiscal_month) 반영:
  corporations.fiscal_month 기준으로 회계연도의 4개 기간(Q1/H1/Q3/FY)을
  동일 fiscal_year로 묶어 격자를 구성한다.
  fiscal_month=12이면 12월 결산사(기존과 동일).

사용법:
    python3 scripts/check_period_completeness.py [옵션]

옵션:
    --market    KOSPI | KOSDAQ (기본: 전체)
    --corp      특정 기업 corp_code (단건 조회)
    --since     기준 fiscal_year (기본: 2000)
    --output    summary 파일 경로 (기본: period_completeness.txt)
    --log-dir   기업별 로그 디렉터리 (기본: logs/coverage)
    --no-logs   기업별 로그 생성 안 함

출력:
    - period_completeness.txt    : 전체 요약 + 갭 기업 목록
    - logs/coverage/{code}_{name}.missing_download.log : 갭 기업별 최신 로그
    - logs/coverage/_INDEX_download.txt               : 갭 기업 인덱스
"""
import argparse
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"

# ── 기간 정의 ─────────────────────────────────────────────────────────────────
PERIODS = ["Q1", "H1", "Q3", "FY"]
# 회계연도 내 시간순 (Q1 → H1 → Q3 → FY)
PERIOD_RANK = {"Q1": 0, "H1": 1, "Q3": 2, "FY": 3}

# 제출 마감 (결산기말 기준 + 여유일): 탐지 대상 기간 판단에 사용
# 기말일로부터 이 일수가 지나면 제출이 도래한 것으로 간주
FILING_GRACE_DAYS = {
    "Q1": 45,
    "H1": 45,
    "Q3": 45,
    "FY": 90,
}


# ── DB 조회 ──────────────────────────────────────────────────────────────────

def fetch_corps(market, corp_code) -> list[dict]:
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    # 정기보고 미대상(펀드/집합투자기구 등 non_periodic)은 완전성 모집단에서 제외
    clauses = ["is_active = TRUE", "COALESCE(coverage_class,'periodic') <> 'non_periodic'"]
    params = []
    if market:
        clauses.append("market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    cur.execute(f"""
        SELECT corp_code, corp_name, COALESCE(market,'?') AS market,
               COALESCE(fiscal_month, 12) AS fiscal_month
        FROM corporations
        WHERE {where}
        ORDER BY corp_code
    """, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_filings(since_year: int, market, corp_code) -> dict:
    """
    반환: {corp_code: [(fiscal_year, fiscal_period, is_final, dl_status), ...]}
    dl_status: 'completed' | 'pending' | 'failed' | 'skipped' | None
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["c.is_active = TRUE", "f.report_type IS NOT NULL", "f.fiscal_year >= %s"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("c.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    cur.execute(f"""
        SELECT
            f.corp_code,
            f.fiscal_year,
            f.fiscal_period,
            f.is_final,
            COALESCE(dt.status, 'none') AS dl_status
        FROM corporations c
        JOIN filings f ON f.corp_code = c.corp_code
        LEFT JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        WHERE {where}
    """, params)
    result = defaultdict(list)
    for row in cur.fetchall():
        result[row[0]].append(row[1:])
    conn.close()
    return dict(result)


def fetch_corp_first_period(since_year: int, market, corp_code) -> dict:
    """
    반환: {corp_code: (first_fiscal_year, first_fiscal_period)}
          = DB에 등록된 가장 이른(시간순) 공시.

    상장/등록 경계 처리에 사용: 회사의 첫 제출이 H1이면 그 해 Q1은
    애초에 존재하지 않으므로 기대 격자에서 제외(false-positive 방지).
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["c.is_active = TRUE", "f.report_type IS NOT NULL",
               "f.fiscal_year IS NOT NULL", "f.fiscal_year >= %s",
               "f.fiscal_period IN ('Q1','H1','Q3','FY')"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("c.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    # DISTINCT ON으로 corp별 시간순(연도→기간순위) 첫 행 선택
    cur.execute(f"""
        SELECT DISTINCT ON (f.corp_code)
               f.corp_code, f.fiscal_year, f.fiscal_period
        FROM corporations c
        JOIN filings f ON f.corp_code = c.corp_code
        WHERE {where}
        ORDER BY f.corp_code, f.fiscal_year ASC,
                 CASE f.fiscal_period
                     WHEN 'Q1' THEN 0 WHEN 'H1' THEN 1
                     WHEN 'Q3' THEN 2 WHEN 'FY' THEN 3 ELSE 9 END ASC
    """, params)
    result = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()
    return result


def fetch_stub_years(market, corp_code) -> dict:
    """
    반환: {corp_code: set(fiscal_year)} — 결산월 변경 전환 stub 회계연도(PRD 01a).
    이 연도들은 회계기간이 단축/불규칙(예 9개월 stub)이라 Q1/H1/Q3/FY 4기간을
    rigid 하게 기대하면 phantom NOFIL 이 생긴다 → 완전성 격자에서 면제한다.
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["is_stub = TRUE", "fiscal_year IS NOT NULL"]
    params = []
    if corp_code:
        clauses.append("corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)
    cur.execute(f"SELECT DISTINCT corp_code, fiscal_year FROM filings WHERE {where}", params)
    result: dict = {}
    for code, fy in cur.fetchall():
        result.setdefault(code, set()).add(fy)
    conn.close()
    return result


# ── 기간 격자 생성 ────────────────────────────────────────────────────────────

def _period_end_date(fiscal_year: int, period: str, fiscal_month: int) -> date:
    """
    (fiscal_year, period, fiscal_month) → 해당 기간의 결산 기말일.

    fiscal_year는 '결산이 끝나는 해' 기준.
    fiscal_month=FYE 월.

    FY  → (fiscal_year, FYE월, 말일)
    Q3  → FY - 3개월
    H1  → FY - 6개월
    Q1  → FY - 9개월
    """
    import calendar

    def _last_day(y: int, m: int) -> date:
        return date(y, m, calendar.monthrange(y, m)[1])

    if period == "FY":
        return _last_day(fiscal_year, fiscal_month)

    # FY 기말에서 offset개월 전 = 해당 분기 기말
    offset = {"Q3": 3, "H1": 6, "Q1": 9}[period]
    # 월 인덱스(0-based month): year*12 + (month-1)
    month_index = fiscal_year * 12 + (fiscal_month - 1) - offset
    y = month_index // 12
    m = month_index % 12 + 1
    return _last_day(y, m)


def build_expected_grid(
    first_fy: int,
    first_period: str,
    fiscal_month: int,
    today: date,
    since_year: int,
) -> list[tuple[int, str]]:
    """
    (fiscal_year, period) 조합 중 제출 마감이 지난 기간만 반환.

    상장/등록 경계: 첫 회계연도(first_fy)에서는 회사의 실제 첫 제출 기간
    (first_period) 이전 분기를 제외한다. (예: 첫 공시가 H1이면 그 해 Q1 제외)
    단 first_fy가 since_year보다 이르면(이미 since_year 이전 상장) 경계 처리 불필요.
    """
    current_fy = today.year + (1 if today.month > fiscal_month else 0)
    first_rank = PERIOD_RANK.get(first_period, 0)
    grid = []
    for fy in range(max(first_fy, since_year), current_fy + 1):
        for p in PERIODS:
            # 상장 첫 해의 첫 제출 이전 분기 제외 (false-positive NOFIL 방지)
            if fy == first_fy and PERIOD_RANK[p] < first_rank:
                continue
            period_end = _period_end_date(fy, p, fiscal_month)
            deadline = period_end + timedelta(days=FILING_GRACE_DAYS[p])
            if deadline <= today:
                grid.append((fy, p))
    return grid


# ── 셀 상태 판별 ──────────────────────────────────────────────────────────────

def cell_status(
    fy: int,
    period: str,
    filings_map: dict,  # {(fy, period): [(is_final, dl_status), ...]}
) -> str:
    key = (fy, period)
    rows = filings_map.get(key, [])
    if not rows:
        return "NOFIL"
    # is_final 행 우선
    final_rows = [(is_f, dl) for (is_f, dl) in rows if is_f]
    check_rows = final_rows or rows
    for is_f, dl in check_rows:
        if dl == "completed":
            return "OK"
    # filing은 있으나 미다운로드
    return "NODL"


# ── 기업별 로그 출력 ──────────────────────────────────────────────────────────

def _safe_name(corp_name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', corp_name)


def write_corp_log(
    corp: dict,
    grid: list[tuple[int, str]],
    filings_map: dict,
    log_dir: Path,
    today: date,
    stub_set: set = frozenset(),
) -> bool:
    """
    갭(NODL/NOFIL)이 있으면 로그 작성 후 True 반환.
    갭이 없으면 기존 로그 삭제 후 False 반환.
    """
    code = corp["corp_code"]
    name = corp["corp_name"]
    safe = _safe_name(name)
    log_path = log_dir / f"{code}_{safe}.missing_download.log"

    gaps = [(fy, p) for (fy, p) in grid
            if fy not in stub_set and cell_status(fy, p, filings_map) != "OK"]

    if not gaps:
        if log_path.exists():
            log_path.unlink()
        return False

    lines = []
    lines.append(f"# {code}  {name}  [{corp['market']}]  결산월={corp['fiscal_month']}월")
    lines.append(f"# 생성: {today.isoformat()}  (이 파일은 최신본으로 덮어써집니다)")
    lines.append(f"# 갭 {len(gaps)}건 / 전체 {len(grid)}건")
    lines.append("")
    lines.append(f"  {'연도':>6}  {'기간':<4}  상태    권장 조치")
    lines.append(f"  {'──────':>6}  {'────':<4}  ──────  ──────────────────────────")

    for fy, p in gaps:
        st = cell_status(fy, p, filings_map)
        if st == "NOFIL":
            action = f"python run.py sync-filings --corp {code} --force  → download"
        else:  # NODL
            action = f"python run.py download --corp {code}"
        lines.append(f"  {fy:>6}  {p:<4}  {st:<6}  {action}")

    lines.append("")
    lines.append("# 상태 코드:")
    lines.append("#   NOFIL  — DART 공시 미등록. force 재싱크로 확인 필요")
    lines.append("#   NODL   — 공시는 있으나 파일 미다운로드 또는 실패")
    lines.append("")

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return True


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="기대 기간 대비 다운로드 완전성 검증")
    ap.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    ap.add_argument("--corp", default=None, metavar="CORP_CODE")
    ap.add_argument("--since", type=int, default=2000)
    ap.add_argument("--output", default="period_completeness.txt")
    ap.add_argument("--log-dir", default="logs/coverage")
    ap.add_argument("--no-logs", action="store_true")
    args = ap.parse_args()

    today = date.today()
    log_dir = Path(args.log_dir)
    if not args.no_logs:
        log_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] 기업 목록 조회 (market={args.market or '전체'}, since={args.since})...")
    corps = fetch_corps(args.market, args.corp)
    print(f"      → {len(corps):,}개 기업")

    print("[2/4] 공시/다운로드 현황 조회...")
    raw_filings = fetch_filings(args.since, args.market, args.corp)
    first_periods = fetch_corp_first_period(args.since, args.market, args.corp)
    stub_years = fetch_stub_years(args.market, args.corp)  # PRD 01a: 전환 stub 연도 면제

    print("[3/4] 격자 분석 중...")

    # 요약 통계
    total_cells = 0
    ok_cells = 0
    nodl_cells = 0
    nofil_cells = 0
    exempt_cells = 0  # 결산변경 stub 연도 면제(phantom 방지)
    gap_corps: list[dict] = []
    nofil_corps: list[str] = []

    summary_lines: list[str] = []

    for corp in corps:
        code = corp["corp_code"]
        fm = corp["fiscal_month"]
        first_fy, first_period = first_periods.get(code, (today.year, "Q1"))

        grid = build_expected_grid(first_fy, first_period, fm, today, args.since)
        if not grid:
            continue

        # 이 기업의 공시를 (fy, period) → [(is_final, dl_status)] 맵으로
        corp_filings = raw_filings.get(code, [])
        filings_map: dict[tuple, list] = defaultdict(list)
        for fy, period, is_final, dl_status in corp_filings:
            if period in PERIODS:
                filings_map[(fy, period)].append((is_final, dl_status))

        corp_stubs = stub_years.get(code, set())
        corp_ok = corp_nodl = corp_nofil = corp_exempt = 0
        for fy, p in grid:
            st = cell_status(fy, p, filings_map)
            if st == "OK":
                corp_ok += 1
            elif fy in corp_stubs:
                # 전환 stub 회계연도: 단축·불규칙 기간이라 결손을 갭으로 보지 않음(면제)
                corp_exempt += 1
            elif st == "NODL":
                corp_nodl += 1
            else:
                corp_nofil += 1

        total_cells += len(grid)
        ok_cells += corp_ok
        nodl_cells += corp_nodl
        nofil_cells += corp_nofil
        exempt_cells += corp_exempt

        has_gap = (corp_nodl + corp_nofil) > 0
        if has_gap:
            gap_corps.append(corp)
            if corp_nofil > 0:
                nofil_corps.append(code)

        if not args.no_logs:
            write_corp_log(corp, grid, filings_map, log_dir, today, corp_stubs)

    print("[4/4] 출력 생성...")

    out_lines = []
    out_lines.append("=" * 90)
    out_lines.append("  TJ Finance — Period Completeness Verification")
    out_lines.append(f"  Generated : {today.isoformat()}")
    out_lines.append(f"  Market    : {args.market or '전체'}")
    out_lines.append(f"  Since     : {args.since}")
    out_lines.append(f"  Cells     : 기대 기간 셀 총계")
    out_lines.append("=" * 90)
    out_lines.append("")
    out_lines.append("  셀 상태 코드:")
    out_lines.append("    OK     — 다운로드 완료")
    out_lines.append("    NODL   — filing 등록됐으나 미다운로드/실패")
    out_lines.append("    NOFIL  — DART 공시 미등록 (force 재싱크 후 재확인)")
    out_lines.append("    FUTURE — 제출 마감 미도래 (집계 제외)")
    out_lines.append("")
    out_lines.append("=" * 90)
    out_lines.append("  커버리지 요약")
    out_lines.append("=" * 90)
    out_lines.append(f"  대상 기업 수       : {len(corps):,}")
    out_lines.append(f"  기대 기간 총 셀    : {total_cells:,}")
    out_lines.append(f"  OK                 : {ok_cells:,}  ({ok_cells/total_cells*100:.1f}%)" if total_cells else "  OK                 : 0")
    out_lines.append(f"  NODL (미다운로드)  : {nodl_cells:,}  ({nodl_cells/total_cells*100:.1f}%)" if total_cells else "  NODL               : 0")
    out_lines.append(f"  NOFIL (미등록)     : {nofil_cells:,}  ({nofil_cells/total_cells*100:.1f}%)" if total_cells else "  NOFIL              : 0")
    out_lines.append(f"  EXEMPT (전환stub)  : {exempt_cells:,}  (결산변경 전환연도 면제, PRD 01a)")
    out_lines.append(f"  갭 있는 기업 수    : {len(gap_corps):,} / {len(corps):,}")
    out_lines.append("")

    if gap_corps:
        out_lines.append(f"  ── NODL/NOFIL 갭 있는 기업 ({len(gap_corps)}개) ──")
        for corp in gap_corps[:300]:
            out_lines.append(f"    {corp['corp_code']}  {corp['corp_name']:30s}  [{corp['market']}]  결산월={corp['fiscal_month']}월")
        if len(gap_corps) > 300:
            out_lines.append(f"    ... 외 {len(gap_corps)-300}개 (로그 파일 참조)")
        out_lines.append("")

    if nofil_corps:
        out_lines.append(f"  ── NOFIL 기업 force 재싱크 명령 ({len(nofil_corps)}개) ──")
        out_lines.append(f"  python run.py sync-filings --force  # 전체 재싱크")
        out_lines.append(f"  또는 기업별: python run.py sync-filings --corp <CODE> --force")
        out_lines.append("")

    if not args.no_logs:
        index_path = log_dir / "_INDEX_download.txt"
        idx_lines = [
            f"# 다운로드 갭 인덱스 — {today.isoformat()}",
            f"# 갭 기업: {len(gap_corps)} / {len(corps)}",
            "",
        ]
        for corp in gap_corps:
            idx_lines.append(
                f"  {corp['corp_code']}  {corp['corp_name']:30s}  [{corp['market']}]"
            )
        index_path.write_text("\n".join(idx_lines), encoding="utf-8")
        out_lines.append(f"  기업별 로그: {log_dir}/{{corp_code}}_{{name}}.missing_download.log")
        out_lines.append(f"  인덱스: {index_path}")

    out_lines.append("=" * 90)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    print(f"완료: {args.output}")
    print(f"  기대 셀 {total_cells:,}개  OK={ok_cells:,}  NODL={nodl_cells:,}  NOFIL={nofil_cells:,}  EXEMPT={exempt_cells:,}")
    print(f"  갭 있는 기업: {len(gap_corps):,}개")
    if not args.no_logs:
        print(f"  기업별 로그: {log_dir}/")


if __name__ == "__main__":
    main()
