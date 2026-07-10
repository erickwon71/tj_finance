"""DEF-4 진단 — calendar_financials 인접연도 CQ1 매출·영업이익 완전동일값 정량화 + 파생방식 분석.

QA 감리(docs/qa/results/defects/DEF-4.md)가 발견한 "같은 기업·같은 statement_type 에서
인접한 두 해의 CQ1 revenue·operating_income 이 소수점까지 동일" 현상을 재현·특성화한다.

- 전수 규모(행/고유조합) 재현
- 연도쌍(prev→next) 분포
- 중복행의 derivation(파생방식) 분포 → 파생버그 vs 원본값 판별의 1차 단서
- 대표 사례(MDS테크 2012/2013, 삼영이엔씨 2017/2018) 원값·derivation·source_lineage 덤프

usage: python scripts/diag_calendar_cq1_dup.py [--dump-list OUT.csv]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import get_session
from sqlalchemy import text

# 인접연도 CQ1 완전동일(매출·영업이익) 페어. version 최신만(있으면), CQ1 = calendar_period='CQ1'.
DUP_SQL = """
WITH cq1 AS (
  SELECT corp_code, statement_type, calendar_year, revenue, operating_income, derivation
  FROM calendar_financials
  WHERE calendar_period = 'CQ1' AND revenue IS NOT NULL
)
SELECT a.corp_code, a.statement_type, a.calendar_year AS prev_year,
       b.calendar_year AS next_year, a.revenue, a.operating_income,
       a.derivation AS prev_deriv, b.derivation AS next_deriv
FROM cq1 a
JOIN cq1 b
  ON a.corp_code = b.corp_code
 AND a.statement_type = b.statement_type
 AND b.calendar_year = a.calendar_year + 1
 AND a.revenue = b.revenue
 AND a.operating_income IS NOT DISTINCT FROM b.operating_income
ORDER BY a.corp_code, a.statement_type, a.calendar_year
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-list")
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(DUP_SQL)).fetchall()
        total_cq1 = s.execute(text(
            "SELECT count(*) FROM calendar_financials "
            "WHERE calendar_period='CQ1' AND revenue IS NOT NULL")).scalar()

    n = len(rows)
    combos = {(r.corp_code, r.statement_type) for r in rows}
    print(f"전체 CQ1(값존재) 행: {total_cq1:,}")
    print(f"인접연도 완전동일 페어: {n:,} (약 {n/total_cq1*100:.2f}%)")
    print(f"영향 고유 (기업,기준) 조합: {len(combos):,}")

    # 연도쌍 분포
    by_pair: dict[str, int] = {}
    for r in rows:
        key = f"{r.prev_year}→{r.next_year}"
        by_pair[key] = by_pair.get(key, 0) + 1
    print("\n=== 연도쌍 분포(상위 12) ===")
    for k, v in sorted(by_pair.items(), key=lambda x: -x[1])[:12]:
        print(f"  {k}: {v:,}")

    # derivation 분포 (prev/next 조합)
    by_deriv: dict[str, int] = {}
    for r in rows:
        key = f"{r.prev_deriv} | {r.next_deriv}"
        by_deriv[key] = by_deriv.get(key, 0) + 1
    print("\n=== derivation(prev | next) 분포(상위 12) ===")
    for k, v in sorted(by_deriv.items(), key=lambda x: -x[1])[:12]:
        print(f"  {k}: {v:,}")

    if args.dump_list:
        with open(args.dump_list, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["corp_code", "statement_type", "prev_year", "next_year",
                        "revenue", "operating_income", "prev_deriv", "next_deriv"])
            for r in rows:
                w.writerow([r.corp_code, r.statement_type, r.prev_year, r.next_year,
                            r.revenue, r.operating_income, r.prev_deriv, r.next_deriv])
        print(f"\n목록 저장: {args.dump_list} ({n:,}행)")


if __name__ == "__main__":
    main()
