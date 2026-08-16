"""
R28 follow-up track T4 -- unit multiplier over-application in report_lines.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §5.)

Found while root-causing the 13 residual R28 keys: three of them vanished because the
table's multiplier (x1,000,000) pushed a genuine value past parse_amount's
`_AMOUNT_SANE_MAX` (1e16, parser/common/amount_normalizer.py:379). The rows that did
NOT exceed the cap were stored 1,000,000x too large instead.

The largest Korean listed company has total assets around 700조 (7e14), so any
|value_won| above 1,000조 (1e15) is arithmetically impossible. Measured 2026-08-16:

  |value_won| > 1e15 :  doc_default 11,570 rows / 559 filings / 256 corps
                        declared    11,150 rows / 364 filings / 172 corps
                        --------------------------------------------------
                        total       22,720 rows / 923 filings

Rows scaled past 1e16 were dropped by parse_amount and are NOT counted here, so the
true damage is larger than these numbers.

★ This probe DETECTS by magnitude only. Do not fix by magnitude -- layer 2's rule is
  that units are never inferred from value size ([[layer2-unit-column-attribution]]).
  The fix must correct how the unit declaration is read. See design doc §5-4.

Usage:
  .venv/bin/python scripts/probe_unit_overscale_2026-08-16.py
  .venv/bin/python scripts/probe_unit_overscale_2026-08-16.py --threshold 1e14
  .venv/bin/python scripts/probe_unit_overscale_2026-08-16.py --csv <path>
"""
import argparse
import csv
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text                       # noqa: E402

from collector.db import get_session              # noqa: E402

# 1,000조 -- above the largest plausible Korean balance-sheet figure by a wide margin.
DEFAULT_THRESHOLD = 1_000_000_000_000_000
DEFAULT_CSV = os.path.join(
    _REPO_ROOT, "scripts", "probe_unit_overscale_2026-08-16_results.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="abs(value_won) above which a row is deemed impossible")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--sample-limit", type=int, default=10)
    args = ap.parse_args()
    thr = int(args.threshold)
    print(f"threshold: |value_won| > {thr:,}")

    with get_session() as s:
        print("\n=== A. scope by unit_source ===")
        total = 0
        for r in s.execute(text("""
            SELECT unit_source, count(*) AS rows,
                   count(DISTINCT rcept_no) AS filings,
                   count(DISTINCT corp_code) AS corps
            FROM report_lines WHERE abs(value_won) > :t
            GROUP BY 1 ORDER BY 2 DESC
        """), {"t": thr}):
            total += r.rows
            print(f"  {(r.unit_source or 'NULL'):14s} rows={r.rows:7,}  "
                  f"filings={r.filings:6,}  corps={r.corps:5,}")
        print(f"  {'TOTAL':14s} rows={total:7,}")

        print("\n=== B. by statement ===")
        for r in s.execute(text("""
            SELECT statement, count(*) AS rows, count(DISTINCT rcept_no) AS filings
            FROM report_lines WHERE abs(value_won) > :t
            GROUP BY 1 ORDER BY 2 DESC
        """), {"t": thr}):
            print(f"  {r.statement:6s} rows={r.rows:7,}  filings={r.filings:6,}")

        print("\n=== C. by era (report_fiscal_year, 5-year buckets) ===")
        for r in s.execute(text("""
            SELECT report_fiscal_year / 5 * 5 AS era, count(*) AS rows,
                   count(DISTINCT corp_code) AS corps
            FROM report_lines WHERE abs(value_won) > :t
            GROUP BY 1 ORDER BY 1
        """), {"t": thr}):
            print(f"  {r.era}~  rows={r.rows:7,}  corps={r.corps:5,}")

        print("\n=== D. by declared adecimal (unit exponent) ===")
        for r in s.execute(text("""
            SELECT adecimal, unit_source, count(*) AS rows
            FROM report_lines WHERE abs(value_won) > :t
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12
        """), {"t": thr}):
            print(f"  adecimal={str(r.adecimal):>4s}  "
                  f"{(r.unit_source or 'NULL'):14s} rows={r.rows:7,}")

        print(f"\n=== E. samples (first {args.sample_limit}) ===")
        for r in s.execute(text("""
            SELECT rcept_no, corp_code, statement, basis, adecimal, unit_source,
                   value_won, value_raw,
                   left(regexp_replace(label_raw, '\\s+', ' ', 'g'), 60) AS label
            FROM report_lines WHERE abs(value_won) > :t
            ORDER BY abs(value_won) DESC LIMIT :lim
        """), {"t": thr, "lim": args.sample_limit}):
            print(f"  {r.rcept_no} {r.corp_code} {r.statement}/{r.basis} "
                  f"adecimal={r.adecimal} src={r.unit_source}")
            print(f"      value_won={r.value_won:,}  value_raw={r.value_raw!r}")
            print(f"      {r.label}")

        print("\n=== F. writing per-filing CSV ===")
        rows = s.execute(text("""
            SELECT rl.rcept_no, rl.corp_code, f.fiscal_year, f.fiscal_period,
                   rl.statement, rl.basis, rl.unit_source, rl.adecimal,
                   count(*) AS n_impossible_rows, max(abs(rl.value_won)) AS max_abs
            FROM report_lines rl JOIN filings f USING (rcept_no)
            WHERE abs(rl.value_won) > :t
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
            ORDER BY n_impossible_rows DESC
        """), {"t": thr}).fetchall()
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["rcept_no", "corp_code", "fiscal_year", "fiscal_period",
                        "statement", "basis", "unit_source", "adecimal",
                        "n_impossible_rows", "max_abs_value_won"])
            for r in rows:
                w.writerow(list(r))
        print(f"  {len(rows)} groups -> {args.csv}")
        print("\n  Next (design doc T4-1/T4-2): cross-check the top groups against the "
              "source XML's unit declaration text before proposing any fix.")


if __name__ == "__main__":
    main()
