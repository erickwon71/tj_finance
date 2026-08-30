#!/usr/bin/env python
"""valuation_daily_v3_migration_plan_2026-08-30.md §Phase 0-1 실측 스크립트.

v2 vs v3 값 대조(ebitda/net_debt/operating_income/ni/eq) — 다양한 시대/basis 표본.
report_tables_note_backfill_plan_2026-08-30.md §Phase 2-2("표본 재대조") 검증용으로도
그대로 재사용한다 — 백필 전/후 실행해 불일치율(2026-08-30 백필 전 실측: 20건 중 7건,
35%)이 얼마나 줄었는지 비교.

선정 기준: FY, 두 basis 모두, 시대별로 층화(1999~2010 / 2011~2019 / 2020~2023 /
2024~2025 — 마지막 구간이 cf_da_sync 패치 대상이라 가장 중요) — 각 층에서 v2·v3
둘 다 값이 있는 corp 중 다섯 개씩 무작위 추출(매 실행 무작위라 건수는 20 근방에서 변동 가능).
"""
import psycopg2

conn = psycopg2.connect("dbname=tj_finance host=localhost")
cur = conn.cursor()

STRATA = [(1999, 2010), (2011, 2019), (2020, 2023), (2024, 2025)]

sample_keys = []
for lo, hi in STRATA:
    cur.execute("""
        SELECT v2.corp_code, v2.fiscal_year, v2.statement_type
        FROM std_financials_v2 v2
        JOIN std_financials_v3 v3
          ON v3.corp_code = v2.corp_code AND v3.fiscal_year = v2.fiscal_year
         AND v3.fiscal_period = 'FY' AND v3.statement_type = v2.statement_type
        WHERE v2.fiscal_period = 'FY' AND v2.version = 1
          AND NOT COALESCE(v2.is_stub, false) AND NOT COALESCE(v2.is_discrete, false)
          AND v2.fiscal_year BETWEEN %s AND %s
        ORDER BY random()
        LIMIT 5
    """, (lo, hi))
    rows = cur.fetchall()
    sample_keys.extend(rows)
    print(f"[{lo}-{hi}] 표본 {len(rows)}건")

print(f"\n총 표본 {len(sample_keys)}건\n")

COLS = ["ebitda", "net_debt", "operating_income"]
mismatches = []
checked = 0
for corp, fy, basis in sample_keys:
    cur.execute(f"""
        SELECT {", ".join(COLS)}, COALESCE(controlling_ni, net_income) AS ni,
               COALESCE(controlling_equity, total_equity) AS eq
        FROM std_financials_v2
        WHERE corp_code=%s AND fiscal_year=%s AND fiscal_period='FY'
          AND statement_type=%s AND version=1
    """, (corp, fy, basis))
    v2row = cur.fetchone()
    cur.execute(f"""
        SELECT {", ".join(COLS)}, COALESCE(controlling_ni, net_income) AS ni,
               COALESCE(controlling_equity, total_equity) AS eq
        FROM std_financials_v3
        WHERE corp_code=%s AND fiscal_year=%s AND fiscal_period='FY'
          AND statement_type=%s
    """, (corp, fy, basis))
    v3row = cur.fetchone()
    checked += 1
    if v2row != v3row:
        mismatches.append((corp, fy, basis, v2row, v3row))

print(f"대조 {checked}건 중 불일치 {len(mismatches)}건 "
      f"({100 * len(mismatches) / checked:.0f}%, 백필 전 baseline = 35%)\n")
for corp, fy, basis, v2row, v3row in mismatches:
    print(f"  {corp} FY{fy} {basis}:")
    print(f"    v2 = {v2row}")
    print(f"    v3 = {v3row}")
