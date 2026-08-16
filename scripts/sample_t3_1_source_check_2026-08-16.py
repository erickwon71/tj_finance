"""
R28 follow-up track T3-1 -- source-cross-check sampling helper.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §6 T3-1.)

Pulls the full detail needed to manually cross-check §4-1 D's claim (1,142 of the
1,187 net_income-NULL cells already hold an R28 headline row in report_lines) against
the source XML for a hand-picked sample:
  - rcept_no + file_path (to open the source XML)
  - table_seq / row_order / col_index (to locate the exact row+cell)
  - value_won / adecimal / unit_source / value_raw (to check unit application)
  - label_raw (to check it is really the headline NI row, not a false-positive
    substring match on '순이익' + '주당')

Read-only. No DB writes.

Usage:
  .venv/bin/python scripts/sample_t3_1_source_check_2026-08-16.py
  .venv/bin/python scripts/sample_t3_1_source_check_2026-08-16.py --rcept 20031114000665,...
"""
import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text                       # noqa: E402

from collector.db import get_session               # noqa: E402

# measure_r28_net_income_gap_2026-08-16.py has a dash in its filename so it can't be
# imported by module path; inline the two CTEs + key loader instead (kept identical).
import json  # noqa: E402

CURATED_KEYS = os.path.join(
    _REPO_ROOT, "fin2", "extract", "data",
    "eps_kgaap_headline_not_eps_keys_2026-08-15.json")

BASIS_TO_STATEMENT_TYPE = {"consolidated": "consolidated", "separate": "separate"}

_TGT_CTE = """
    tgt AS (
      SELECT DISTINCT f.corp_code, f.fiscal_year, f.fiscal_period, p.statement_type
      FROM _r28_pop p JOIN filings f USING (rcept_no)
    )
"""
_NULLS_CTE = _TGT_CTE + """,
    nulls AS (
      SELECT t.* FROM tgt t
      LEFT JOIN std_financials_v3 v
        ON v.corp_code = t.corp_code AND v.fiscal_year = t.fiscal_year
       AND v.fiscal_period = t.fiscal_period AND v.statement_type = t.statement_type
      WHERE v.net_income IS NULL
    )
"""


def load_pairs():
    with open(CURATED_KEYS, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("keys", raw.get("rows", []))
    keys = [tuple(k) for k in raw]
    pairs = sorted({(k[0], BASIS_TO_STATEMENT_TYPE.get(k[2], k[2])) for k in keys})
    return keys, pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept", help="comma-separated rcept_no allowlist (optional filter)")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    _, pairs = load_pairs()
    rcept_filter = set(args.rcept.split(",")) if args.rcept else None

    with get_session() as s:
        s.execute(text("CREATE TEMP TABLE _r28_pop "
                       "(rcept_no text, statement_type text) ON COMMIT DROP"))
        s.execute(text("INSERT INTO _r28_pop (rcept_no, statement_type) VALUES (:r, :t)"),
                  [{"r": r, "t": t} for r, t in pairs])

        rows = s.execute(text(f"""
            WITH {_NULLS_CTE}
            SELECT f2.rcept_no, n.corp_code, n.fiscal_year, n.fiscal_period,
                   n.statement_type AS basis,
                   rl.table_seq, rl.row_order, rl.col_index, rl.depth,
                   rl.value_won, rl.adecimal, rl.unit_source, rl.value_raw,
                   left(regexp_replace(rl.label_raw, '\\s+', ' ', 'g'), 140) AS label,
                   dt.file_path
            FROM nulls n
            JOIN filings f2 ON f2.corp_code = n.corp_code
                           AND f2.fiscal_year = n.fiscal_year
                           AND f2.fiscal_period = n.fiscal_period
            JOIN report_lines rl ON rl.rcept_no = f2.rcept_no AND rl.statement = 'IS'
                                AND rl.basis = n.statement_type
                                AND rl.row_order IS NOT NULL
            LEFT JOIN download_tasks dt ON dt.rcept_no = f2.rcept_no AND dt.file_type = 'xml'
            WHERE rl.label_raw LIKE '%순이익%' AND rl.label_raw LIKE '%주당%'
            ORDER BY n.statement_type, n.fiscal_year, f2.rcept_no
            LIMIT :lim
        """), {"lim": args.limit}).fetchall()

        for row in rows:
            if rcept_filter and row.rcept_no not in rcept_filter:
                continue
            print(f"\nrcept={row.rcept_no}  corp={row.corp_code}  "
                  f"{row.fiscal_year}{row.fiscal_period}  basis={row.basis}")
            print(f"  table_seq={row.table_seq} row_order={row.row_order} "
                  f"col_index={row.col_index} depth={row.depth}")
            print(f"  value_won={row.value_won:,}  adecimal={row.adecimal}  "
                  f"unit_source={row.unit_source}  value_raw={row.value_raw!r}")
            print(f"  label={row.label}")
            print(f"  file_path={row.file_path}")


if __name__ == "__main__":
    main()
