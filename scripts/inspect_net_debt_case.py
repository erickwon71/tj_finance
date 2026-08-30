"""Ad-hoc read-only inspector for one (corp_code, fiscal_year) net_debt case: prints
the face BS (table_seq=0, FY, 연결/별도) debt/bond-labeled rows alongside std_financials_v2
and std_financials_v3's short_term_debt/long_term_debt/net_debt, side by side.

Used to verify a step's net_debt fix against the ORIGINAL filing, not just against v2 —
v2 is not always correct (see docs/plans/valuation_daily_blockers_da_netdebt_design_
2026-08-30.md §2-7, 삼성전자 반례) — per [[feedback-verify-against-source]].

Usage:
    python scripts/inspect_net_debt_case.py 00126380 2024 --basis consolidated
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text

DB_URL = "postgresql://localhost/tj_finance"

FACE_ROWS_SQL = """
SELECT label_raw, section_path, value_won, col_label, period_kind, is_cumulative
FROM report_lines
WHERE corp_code = :corp AND report_fiscal_year = :fy AND report_fiscal_period = 'FY'
  AND statement = 'BS' AND basis = :basis AND table_seq = 0
  AND (label_raw LIKE '%차입금%' OR label_raw LIKE '%사채%')
ORDER BY row_order;
"""

STD_SQL = """
SELECT 'v3' AS src, short_term_debt, long_term_debt, net_debt, total_liabilities
FROM std_financials_v3
WHERE corp_code = :corp AND fiscal_year = :fy AND fiscal_period = 'FY' AND statement_type = :basis
UNION ALL
SELECT 'v2' AS src, short_term_debt, long_term_debt, net_debt, total_liabilities
FROM std_financials_v2
WHERE corp_code = :corp AND fiscal_year = :fy AND fiscal_period = 'FY' AND statement_type = :basis
  AND version = 1 AND NOT COALESCE(is_discrete, false) AND NOT COALESCE(is_stub, false);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corp_code")
    ap.add_argument("fiscal_year", type=int)
    ap.add_argument("--basis", default="consolidated", choices=["consolidated", "separate"])
    args = ap.parse_args()

    eng = create_engine(DB_URL)
    with eng.connect() as c:
        rows = c.execute(text(FACE_ROWS_SQL),
                          {"corp": args.corp_code, "fy": args.fiscal_year, "basis": args.basis}).fetchall()
        std = c.execute(text(STD_SQL),
                         {"corp": args.corp_code, "fy": args.fiscal_year, "basis": args.basis}).fetchall()

    print(f"=== {args.corp_code} FY{args.fiscal_year} {args.basis} — face BS (table_seq=0) ===")
    for label, section, val, col_label, period_kind, cum in rows:
        print(f"  {label!r:40} {section or '':25} {val:>20} col={col_label!r} {period_kind} cum={cum}")

    print()
    print("=== std_financials 비교 ===")
    for src, st, lt, nd, tl in std:
        print(f"  {src}: short_term_debt={st} long_term_debt={lt} net_debt={nd} total_liabilities={tl}")


if __name__ == "__main__":
    main()
