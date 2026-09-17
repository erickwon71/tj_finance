"""SCE(자본변동표) 2015+ 이상치 스캔 — BS/IS/CF와 같은 방법론.

1단계: is_final=TRUE 유니버스에서 rcept×basis별 SCE 행수 분포를 뽑아
히스토그램으로 자연스러운 저조 임계값을 정한다(임의 숫자를 먼저 정하지 않음).

사용:
    python scripts/scan_sce_2015plus_2026-09-16.py --histogram
    python scripts/scan_sce_2015plus_2026-09-16.py --threshold-consolidated N --threshold-separate M
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_UNIVERSE_FILTER = """
    c.is_active
    AND c.stock_code IS NOT NULL
    AND c.stock_code NOT LIKE '9%'
    AND c.coverage_class = 'periodic'
"""

_FILING_FILTER = """
    f.report_type IN ('annual','half','quarter')
    AND f.fiscal_year >= 2015
    AND f.is_final = TRUE
    AND f.report_nm NOT LIKE '%제출기한연장%'
"""

_ROWCOUNT_SQL = f"""
    SELECT rl.rcept_no, rl.basis, count(*) AS n_rows,
           count(DISTINCT rl.table_seq) AS n_tables
    FROM report_lines rl
    JOIN filings f ON f.rcept_no = rl.rcept_no
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE rl.statement = 'SCE'
      AND {_UNIVERSE_FILTER}
      AND {_FILING_FILTER}
    GROUP BY rl.rcept_no, rl.basis
"""


def histogram():
    with get_session() as s:
        rows = s.execute(text(_ROWCOUNT_SQL)).fetchall()
    print(f"총 rcept×basis 조합: {len(rows):,}")
    by_basis: dict[str, Counter] = {"consolidated": Counter(), "separate": Counter()}
    for r in rows:
        if r.basis in by_basis:
            by_basis[r.basis][r.n_rows] += 1
    for basis, counter in by_basis.items():
        total = sum(counter.values())
        print(f"\n=== {basis} (n={total:,}) ===")
        for n_rows in sorted(counter)[:40]:
            cnt = counter[n_rows]
            bar = "#" * min(cnt, 60)
            print(f"  {n_rows:4d} rows: {cnt:6,}  {bar}")


def list_low(threshold_consolidated: int, threshold_separate: int):
    thresholds = {"consolidated": threshold_consolidated, "separate": threshold_separate}
    sql = f"""
        SELECT rl.rcept_no, rl.basis, count(*) AS n_rows,
               f.corp_code, c.corp_name, c.stock_code, f.fiscal_year, f.fiscal_period, f.report_nm
        FROM report_lines rl
        JOIN filings f ON f.rcept_no = rl.rcept_no
        JOIN corporations c ON c.corp_code = f.corp_code
        WHERE rl.statement = 'SCE'
          AND {_UNIVERSE_FILTER}
          AND {_FILING_FILTER}
        GROUP BY rl.rcept_no, rl.basis, f.corp_code, c.corp_name, c.stock_code, f.fiscal_year, f.fiscal_period, f.report_nm
        HAVING count(*) <= :thr
        ORDER BY count(*), c.corp_name
    """
    with get_session() as s:
        for basis, thr in thresholds.items():
            rows = s.execute(text(sql.replace(":thr", str(thr)))).fetchall()
            rows = [r for r in rows if r.basis == basis]
            print(f"\n=== {basis} <= {thr} rows: {len(rows)}건 ===")
            for r in rows:
                print(f"  {r.n_rows:4d}  {r.corp_name}({r.stock_code}) {r.fiscal_year} "
                      f"{r.fiscal_period} {r.rcept_no}  {r.report_nm}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--histogram", action="store_true")
    ap.add_argument("--threshold-consolidated", type=int)
    ap.add_argument("--threshold-separate", type=int)
    args = ap.parse_args()

    if args.histogram:
        histogram()
    elif args.threshold_consolidated is not None or args.threshold_separate is not None:
        list_low(args.threshold_consolidated or 0, args.threshold_separate or 0)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
