"""
Unit Consistency Audit
=======================
financial_facts.amount 의 단위 정합성을 3가지 휴리스틱으로 검사한다.

배경:
  parse_amount()가 unit_multiplier를 곱해 amount를 원 단위로 저장한다.
  그러나 unit_multiplier 탐지가 실패하면 천원·백만원 단위 그대로 저장되어
  실제값보다 1000x / 1,000,000x 작게 들어갈 수 있다.
  (반대로 중복 곱셈이면 1000x 크게 들어간다.)

검사 규칙:
  ① 동일 (rcept_no, fs_type, source_format) 내 unit_multiplier 혼재
     → source_format으로 분리: XBRL(unit=1, 이미 완전 원값)과 텍스트표(unit≥1000,
       헤더 스케일)의 정상 공존은 제외. 같은 source_format 안에서만 혼재 = 진짜 오류
       (예: xml_text 표 일부 천원·일부 단위미탐지 원 디폴트 → 1000x 과소)
  ② 연속 기간 값 점프 ≈ 1000x 또는 ≈ 1e6x
     → 동일 (corp, account_code, statement_type) 에서 인접 FY 비율이 급변
  ③ BS 자산 vs 부채+자본 스케일 불일치
     → 자산과 (부채+자본)의 자릿수 차이가 3자리 이상이면 단위 불일치 의심

출력:
  - 의심 filing 목록 (rcept_no, 규칙, 상세)
  - 교정 방법: python run.py parse-reset → parse

사용법:
    python3 scripts/audit_unit_consistency.py [옵션]

옵션:
    --market  KOSPI | KOSDAQ
    --corp    특정 기업 corp_code
    --since   기준 fiscal_year (기본: 2010)
    --output  결과 파일 (기본: unit_audit.txt)
    --ratio-threshold  연속 기간 비율 임계값 (기본: 500, ≈1000x의 절반)
"""
import argparse
from datetime import date

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"
UNIT = 100_000_000  # 억원


# ── DB 조회 ──────────────────────────────────────────────────────────────────

def fetch_mixed_unit(since_year: int, market, corp_code,
                     limit: int = 500) -> tuple[list[dict], int]:
    """
    규칙 ①: 동일 (rcept_no, fs_type, **source_format**) 내 unit_multiplier 혼재 탐지.

    중요: source_format으로 분리한다.
      XBRL(xbrl_acode/note_xml)은 이미 완전한 원 값 → unit_multiplier=1 (정상),
      텍스트표(xml_text)는 헤더 단위(천원=1000 등) 스케일 → unit_multiplier≥1000 (정상).
      한 재무제표에 둘이 공존하는 것은 정상이며 amount는 양쪽 모두 원으로 정규화됨.
    따라서 **같은 source_format 안에서** unit이 섞인 경우만 진짜 오류로 본다
      (예: xml_text 표가 일부는 천원, 일부는 단위미탐지로 원 디폴트 → 1000x 과소).

    반환: (상위 limit개 행, 전체 의심 그룹 수)
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    clauses = ["ff.fiscal_year >= %s", "dt.file_type = 'xml'",
               "dt.parse_status IN ('success', 'partial')"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("ff.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)

    base = f"""
        FROM financial_facts ff
        JOIN download_tasks dt ON dt.rcept_no = ff.rcept_no
        JOIN corporations c ON c.corp_code = ff.corp_code
        WHERE {where}
          AND ff.unit_multiplier > 0
          AND NOT ff.is_superseded
        GROUP BY ff.rcept_no, ff.corp_code, c.corp_name, ff.fs_type,
                 ff.fiscal_year, ff.fiscal_period, ff.source_format
        HAVING COUNT(DISTINCT ff.unit_multiplier) > 1
    """

    # 상세 목록 (상위 limit개)
    cur.execute(f"""
        SELECT
            ff.rcept_no, ff.corp_code, c.corp_name, ff.fs_type,
            ff.fiscal_year, ff.fiscal_period, ff.source_format,
            COUNT(DISTINCT ff.unit_multiplier) AS unit_kinds,
            ARRAY_AGG(DISTINCT ff.unit_multiplier ORDER BY ff.unit_multiplier) AS units
        {base}
        ORDER BY ff.corp_code, ff.fiscal_year DESC, ff.rcept_no
        LIMIT {int(limit)}
    """, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # 전체 의심 그룹 수
    cur.execute(f"SELECT COUNT(*) FROM ( SELECT 1 {base} ) t", params)
    total = cur.fetchone()[0]

    conn.close()
    return rows, total


def fetch_jump_candidates(since_year: int, market, corp_code,
                          ratio_threshold: float) -> list[dict]:
    """
    규칙 ②: 연속 FY 간 값 비율 이상 (≈1000x or ≈1e6x 점프)
    revenue, total_assets 만 검사 (이상치가 가장 잘 드러남)
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    clauses = ["sf.fiscal_year >= %s", "sf.fiscal_period = 'FY'"]
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
            sf.corp_code,
            c.corp_name,
            sf.fiscal_year,
            sf.statement_type,
            sf.revenue,
            sf.total_assets,
            LAG(sf.revenue) OVER w AS prev_revenue,
            LAG(sf.total_assets) OVER w AS prev_assets,
            LAG(sf.fiscal_year) OVER w AS prev_year
        FROM standard_financials sf
        JOIN corporations c ON c.corp_code = sf.corp_code
        WHERE {where}
        WINDOW w AS (PARTITION BY sf.corp_code, sf.statement_type ORDER BY sf.fiscal_year)
        ORDER BY sf.corp_code, sf.fiscal_year
    """, params)

    results = []
    for row in cur.fetchall():
        (corp_c, corp_name, fy, stmt, rev, assets, prev_rev, prev_assets, prev_fy) = row
        if prev_fy is None or fy - prev_fy != 1:
            continue

        for label, cur_val, prev_val in [("revenue", rev, prev_rev),
                                          ("total_assets", assets, prev_assets)]:
            if cur_val is None or prev_val is None:
                continue
            if prev_val == 0 or cur_val == 0:
                continue
            ratio = abs(cur_val) / abs(prev_val)
            big_jump = ratio >= ratio_threshold
            big_drop = ratio <= 1 / ratio_threshold
            if not (big_jump or big_drop):
                continue
            # pre-revenue 성장(영≈0 → 정상)은 단위오류 아님:
            # 폭증(jump)인데 전년값이 10억 미만이면 신규영업/상장초기로 보고 제외.
            # (단위 오파싱은 전년이 정상규모인데 당년이 1000x↑ 폭증하는 패턴)
            if big_jump and abs(prev_val) < 1_000_000_000:
                continue
            results.append({
                    "corp_code": corp_c,
                    "corp_name": corp_name,
                    "fiscal_year": fy,
                    "prev_fiscal_year": prev_fy,
                    "statement_type": stmt,
                    "item": label,
                    "cur_val_awk": cur_val / UNIT,
                    "prev_val_awk": prev_val / UNIT,
                    "ratio": ratio,
                })
    conn.close()
    return results


def fetch_bs_scale_mismatch(since_year: int, market, corp_code) -> list[dict]:
    """
    규칙 ③: BS 자산 vs 부채+자본 자릿수 차이 >= 3
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    clauses = ["sf.fiscal_year >= %s", "sf.fiscal_period = 'FY'",
               "sf.total_assets IS NOT NULL",
               "sf.total_liabilities IS NOT NULL",
               "sf.total_equity IS NOT NULL",
               "sf.total_assets > 0"]
    params = [since_year]
    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("sf.corp_code = %s")
        params.append(corp_code)
    where = " AND ".join(clauses)

    cur.execute(f"""
        SELECT sf.corp_code, c.corp_name, sf.fiscal_year, sf.statement_type,
               sf.total_assets, sf.total_liabilities, sf.total_equity, sf.rcept_no
        FROM standard_financials sf
        JOIN corporations c ON c.corp_code = sf.corp_code
        WHERE {where}
        ORDER BY sf.corp_code, sf.fiscal_year DESC
    """, params)

    results = []
    for row in cur.fetchall():
        corp_c, corp_name, fy, stmt, assets, liab, equity, rcept = row
        rhs = (liab or 0) + (equity or 0)
        if rhs == 0:
            continue
        ratio = assets / rhs
        # 3자릿수 이상 차이 (1000x 이상)
        if ratio >= 1000 or ratio <= 0.001:
            results.append({
                "corp_code": corp_c,
                "corp_name": corp_name,
                "fiscal_year": fy,
                "statement_type": stmt,
                "rcept_no": rcept,
                "assets_awk": assets / UNIT,
                "liab_plus_equity_awk": rhs / UNIT,
                "ratio": ratio,
            })
    conn.close()
    return results


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="단위 정합성 감사")
    ap.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    ap.add_argument("--corp", default=None)
    ap.add_argument("--since", type=int, default=2010)
    ap.add_argument("--output", default="unit_audit.txt")
    ap.add_argument("--ratio-threshold", type=float, default=500.0,
                    dest="ratio_threshold")
    args = ap.parse_args()

    today = date.today()
    print(f"[1/4] 규칙① 단위 혼재 탐지 (동일 source_format 내)...")
    mixed, mixed_total = fetch_mixed_unit(args.since, args.market, args.corp)
    print(f"      → {mixed_total}건 (표시 {len(mixed)}건)")

    print(f"[2/4] 규칙② 연속 기간 점프 탐지 (threshold={args.ratio_threshold}x)...")
    jumps = fetch_jump_candidates(args.since, args.market, args.corp, args.ratio_threshold)
    print(f"      → {len(jumps)}건")

    print(f"[3/4] 규칙③ BS 자산/부채+자본 스케일 불일치...")
    bs_mis = fetch_bs_scale_mismatch(args.since, args.market, args.corp)
    print(f"      → {len(bs_mis)}건")

    print(f"[4/4] 출력...")

    lines = []
    lines.append("=" * 90)
    lines.append("  TJ Finance — Unit Consistency Audit")
    lines.append(f"  Generated : {today.isoformat()}")
    lines.append(f"  Market    : {args.market or '전체'}   Since: {args.since}")
    lines.append("=" * 90)
    lines.append("")
    lines.append(f"  규칙① 단위 혼재    : {mixed_total:,}건  (동일 source_format 내 — XBRL+텍스트 정상 공존 제외)")
    lines.append(f"  규칙② 값 점프      : {len(jumps):,}건  (threshold {args.ratio_threshold}x)")
    lines.append(f"  규칙③ BS 스케일    : {len(bs_mis):,}건  (자산 vs 부채+자본 ≥1000x)")
    lines.append("")

    if mixed:
        lines.append("─" * 90)
        lines.append("  규칙① — 동일 source_format 내 unit_multiplier 혼재 (상위 100건)")
        lines.append("─" * 90)
        lines.append(f"  {'rcept_no':<14}  {'corp':8}  {'fs':<6}  {'fy':>4}  {'fp':<3}  {'source_fmt':<12}  unit종류  권장조치")
        for r in mixed[:100]:
            units_str = "/".join(str(u) for u in (r["units"] or []))
            lines.append(
                f"  {r['rcept_no']:<14}  {r['corp_code']:8}  {r['fs_type']:<6}  "
                f"{r['fiscal_year']:>4}  {r['fiscal_period']:<3}  "
                f"{(r['source_format'] or ''):<12}  {units_str:<8}  parse-reset"
            )
        lines.append("")

    if jumps:
        lines.append("─" * 90)
        lines.append("  규칙② — 연속 FY 값 점프 (상위 100건, 억원 단위)")
        lines.append("─" * 90)
        lines.append(f"  {'corp':8}  {'항목':<12}  {'전년도':>4}  {'전년값(억)':>12}  {'당년도':>4}  {'당년값(억)':>12}  {'비율':>8}")
        for r in sorted(jumps, key=lambda x: x["ratio"], reverse=True)[:100]:
            lines.append(
                f"  {r['corp_code']:8}  {r['item']:<12}  "
                f"{r['prev_fiscal_year']:>4}  {r['prev_val_awk']:>12,.1f}  "
                f"{r['fiscal_year']:>4}  {r['cur_val_awk']:>12,.1f}  "
                f"{r['ratio']:>8.0f}x"
            )
        lines.append("")

    if bs_mis:
        lines.append("─" * 90)
        lines.append("  규칙③ — BS 자산 vs 부채+자본 스케일 불일치 (억원 단위)")
        lines.append("─" * 90)
        lines.append(f"  {'corp':8}  {'corp_name':20}  {'fy':>4}  {'자산(억)':>12}  {'부채+자본(억)':>14}  {'비율':>8}")
        for r in bs_mis[:100]:
            lines.append(
                f"  {r['corp_code']:8}  {r['corp_name'][:20]:20}  "
                f"{r['fiscal_year']:>4}  {r['assets_awk']:>12,.1f}  "
                f"{r['liab_plus_equity_awk']:>14,.1f}  {r['ratio']:>8.0f}x"
            )
        lines.append("")

    total_issues = len(mixed) + len(jumps) + len(bs_mis)
    lines.append("─" * 90)
    lines.append(f"  총 의심 건수: {total_issues}")
    if total_issues:
        lines.append("  교정 방법:")
        lines.append("    python run.py parse-reset  →  python run.py parse")
        lines.append("    (재파싱 후 unit 재탐지·재저장)")
    else:
        lines.append("  ✓ 단위 정합성 이상 없음")
    lines.append("=" * 90)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"완료: {args.output}")
    print(f"  총 의심: {total_issues}건  (①{len(mixed)} ②{len(jumps)} ③{len(bs_mis)})")


if __name__ == "__main__":
    main()
