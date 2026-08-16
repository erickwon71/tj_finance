"""
R28 follow-up track T3-0 -- how much `net_income` is still missing for the R28
curated population, now that R28 is implemented and backfilled?
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §4-1.)

The R28 design doc guessed the fix might have auto-resolved much of the net_income
gap it had spotted in a 15-row sample. This measures it instead. Measured 2026-08-16:

  A. target cells 1,840 | net_income NULL 1,187 (64.5%) | revenue NULL 133 (7.2%)
     -> filings ARE being processed; it is specifically NI mapping that fails.
  B. separate 1,163/1,285 NULL (90.5%) vs consolidated 24/555 (4.3%)
  C. same-era (FY1999~2008) baseline: separate 28.3%, consolidated 23.9%
     -> the curated population is 3.2x worse than its era, so this is a real
        population-specific defect, not pre-existing era-wide sparseness.
  D. of the 1,187 NULL cells, 1,142 (96.2%) already hold an R28 headline row in
     report_lines -> recoverable in layer 3 alone, NO re-extraction needed.

Population = curated keys -> (rcept_no, basis) -> filings -> std_financials_v3 cells.

Caveat kept deliberately visible: section D classifies rows by label substring
(순이익 / 주당 / 차감전), which is an approximation. Confirm against source XML on a
sample before designing on top of it (design doc T3-1).

Usage:
  .venv/bin/python scripts/measure_r28_net_income_gap_2026-08-16.py
  .venv/bin/python scripts/measure_r28_net_income_gap_2026-08-16.py --samples 20
"""
import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text                       # noqa: E402

from collector.db import get_session              # noqa: E402

CURATED_KEYS = os.path.join(
    _REPO_ROOT, "fin2", "extract", "data",
    "eps_kgaap_headline_not_eps_keys_2026-08-15.json")

# The curated key's `basis` and std_financials_v3's `statement_type` use the same
# vocabulary (consolidated / separate); mapped explicitly so a future divergence is
# a visible edit rather than a silent mismatch.
BASIS_TO_STATEMENT_TYPE = {"consolidated": "consolidated", "separate": "separate"}

# Population CTE reused by every query below.
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
    ap.add_argument("--samples", type=int, default=8,
                    help="how many NULL-cell sample rows to print")
    args = ap.parse_args()

    keys, pairs = load_pairs()
    print(f"curated keys={len(keys)}  distinct (rcept, basis)={len(pairs)}  "
          f"distinct rcept={len({k[0] for k in keys})}")

    with get_session() as s:
        s.execute(text("CREATE TEMP TABLE _r28_pop "
                       "(rcept_no text, statement_type text) ON COMMIT DROP"))
        s.execute(text("INSERT INTO _r28_pop (rcept_no, statement_type) VALUES (:r, :t)"),
                  [{"r": r, "t": t} for r, t in pairs])

        print("\n=== A. std_v3 coverage for the curated population ===")
        r = s.execute(text(f"""
            WITH {_TGT_CTE}
            SELECT count(*) AS cells,
                   count(*) FILTER (WHERE v.corp_code IS NULL)      AS no_std_row,
                   count(*) FILTER (WHERE v.net_income IS NULL)     AS ni_null,
                   count(*) FILTER (WHERE v.controlling_ni IS NULL) AS cni_null,
                   count(*) FILTER (WHERE v.revenue IS NULL)        AS rev_null
            FROM tgt t
            LEFT JOIN std_financials_v3 v
              ON v.corp_code = t.corp_code AND v.fiscal_year = t.fiscal_year
             AND v.fiscal_period = t.fiscal_period
             AND v.statement_type = t.statement_type
        """)).fetchone()
        pct = lambda n: f"({100 * n / max(r.cells, 1):.1f}%)"     # noqa: E731
        print(f"  target cells              : {r.cells}")
        print(f"  no std_v3 row at all      : {r.no_std_row}")
        print(f"  net_income NULL           : {r.ni_null} {pct(r.ni_null)}")
        print(f"  controlling_ni NULL       : {r.cni_null} {pct(r.cni_null)}")
        print(f"  revenue NULL (comparison) : {r.rev_null} {pct(r.rev_null)}")

        print("\n=== B. net_income NULL by statement_type ===")
        for row in s.execute(text(f"""
            WITH {_TGT_CTE}
            SELECT t.statement_type, count(*) AS cells,
                   count(*) FILTER (WHERE v.net_income IS NULL) AS ni_null
            FROM tgt t
            LEFT JOIN std_financials_v3 v
              ON v.corp_code = t.corp_code AND v.fiscal_year = t.fiscal_year
             AND v.fiscal_period = t.fiscal_period
             AND v.statement_type = t.statement_type
            GROUP BY 1 ORDER BY 1
        """)):
            p = 100 * row.ni_null / max(row.cells, 1)
            print(f"  {row.statement_type:13s} cells={row.cells:6d}  "
                  f"ni_null={row.ni_null:6d} ({p:.1f}%)")

        print("\n=== C. baseline: ALL corps, same era (FY1999~2008) ===")
        for row in s.execute(text("""
            SELECT statement_type, count(*) AS cells,
                   count(*) FILTER (WHERE net_income IS NULL) AS ni_null
            FROM std_financials_v3
            WHERE fiscal_year BETWEEN 1999 AND 2008
            GROUP BY 1 ORDER BY 1
        """)):
            p = 100 * row.ni_null / max(row.cells, 1)
            print(f"  {row.statement_type:13s} cells={row.cells:6d}  "
                  f"ni_null={row.ni_null:6d} ({p:.1f}%)")

        print("\n=== D. do the NULL cells already hold an NI row in report_lines? ===")
        r = s.execute(text(f"""
            WITH {_NULLS_CTE}
            SELECT count(*) AS null_cells,
                   count(*) FILTER (WHERE EXISTS (
                     SELECT 1 FROM report_lines rl JOIN filings f2 USING (rcept_no)
                     WHERE f2.corp_code = n.corp_code AND f2.fiscal_year = n.fiscal_year
                       AND f2.fiscal_period = n.fiscal_period AND rl.statement = 'IS'
                       AND rl.basis = n.statement_type AND rl.row_order IS NOT NULL
                       AND rl.label_raw LIKE '%순이익%' AND rl.label_raw LIKE '%주당%'
                   )) AS has_r28_headline_row,
                   count(*) FILTER (WHERE EXISTS (
                     SELECT 1 FROM report_lines rl JOIN filings f2 USING (rcept_no)
                     WHERE f2.corp_code = n.corp_code AND f2.fiscal_year = n.fiscal_year
                       AND f2.fiscal_period = n.fiscal_period AND rl.statement = 'IS'
                       AND rl.basis = n.statement_type AND rl.row_order IS NOT NULL
                       AND rl.label_raw LIKE '%순이익%'
                       AND rl.label_raw NOT LIKE '%주당%'
                       AND rl.label_raw NOT LIKE '%차감전%'
                   )) AS has_plain_ni_row
            FROM nulls n
        """)).fetchone()
        print(f"  net_income NULL cells                      : {r.null_cells}")
        print(f"  ...with R28 headline row (순이익 AND 주당) : "
              f"{r.has_r28_headline_row}   <- recoverable in layer 3 alone")
        print(f"  ...with plain NI row (no 주당/차감전)      : {r.has_plain_ni_row}")

        print(f"\n--- sample: R28 headline rows sitting in NULL cells "
              f"(first {args.samples}) ---")
        for row in s.execute(text(f"""
            WITH {_NULLS_CTE}
            SELECT n.corp_code, n.fiscal_year, n.fiscal_period, n.statement_type,
                   rl.value_won,
                   left(regexp_replace(rl.label_raw, '\\s+', ' ', 'g'), 90) AS label
            FROM nulls n
            JOIN filings f2 ON f2.corp_code = n.corp_code
                           AND f2.fiscal_year = n.fiscal_year
                           AND f2.fiscal_period = n.fiscal_period
            JOIN report_lines rl ON rl.rcept_no = f2.rcept_no AND rl.statement = 'IS'
                                AND rl.basis = n.statement_type
                                AND rl.row_order IS NOT NULL
            WHERE rl.label_raw LIKE '%순이익%' AND rl.label_raw LIKE '%주당%'
            LIMIT :lim
        """), {"lim": args.samples}):
            print(f"  {row.corp_code} {row.fiscal_year}{row.fiscal_period} "
                  f"{row.statement_type}  v={row.value_won:,}")
            print(f"      {row.label}")


if __name__ == "__main__":
    main()
