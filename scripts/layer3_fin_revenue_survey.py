"""Survey financial-sector revenue label gaps for L3-4 step2 (READ-ONLY).

For revenue DIFF cases classed fin_catalog (both non-null, differ) or v2only (v3 null,
v2 present) among financial-sector corps (KSIC 64/65/66), collect the actual col0 IS
top-line labels present in report_lines so we know which is.revenue aliases to add/
promote. Also reports how v3 currently disposed of revenue (null / held-conflict).
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session
from parser.common.account_mapper import get_mapper

FIN = "(c.induty_code LIKE '64%' OR c.induty_code LIKE '65%' OR c.induty_code LIKE '66%')"


def main():
    period = "FY"
    mapper = get_mapper()
    with get_session() as s:
        # financial-sector revenue cases where v3 differs from or lacks v2
        rows = s.execute(text(f"""
            SELECT v3.corp_code, c.corp_name, c.induty_code, v3.fiscal_year, v3.statement_type,
                   v3.revenue AS v3rev, v2.revenue AS v2rev,
                   v3.source_rcepts->>'IS' AS rc, v3.conflicts
            FROM std_financials_v3 v3
            JOIN std_financials_v2 v2
              ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
             AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
             AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
            JOIN corporations c ON c.corp_code=v3.corp_code
            WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period=:p AND {FIN}
              AND v2.revenue IS NOT NULL
              AND (v3.revenue IS NULL OR v3.revenue <> v2.revenue)
            ORDER BY v3.corp_code, v3.fiscal_year
        """), {"p": period}).fetchall()

        n_null = sum(1 for r in rows if r[5] is None)
        n_diff = len(rows) - n_null
        print(f"financial-sector revenue mismatch (FY): {len(rows)}  "
              f"(v3 null={n_null}, v3≠v2={n_diff})\n")

        # For each, find which col0 IS line matches v2's revenue value (the label v3
        # should have mapped), and what mapper currently returns for it.
        label_for_v2 = Counter()   # label that carries v2's value → alias gap candidates
        unmapped = Counter()       # those labels the mapper does NOT map to is.revenue
        examples = []
        for corp, name, induty, fy, basis, v3rev, v2rev, rc, conflicts in rows:
            line = s.execute(text("""
                SELECT label_raw FROM report_lines
                WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period='FY'
                  AND basis=:b AND statement='IS' AND col_index=0 AND value_won=:v
                ORDER BY (node_role='F') DESC LIMIT 1
            """), {"c": corp, "y": fy, "b": basis, "v": v2rev}).fetchone()
            if not line:
                label_for_v2["<v2 value not a filed col0 line>"] += 1
                continue
            lbl = line[0]
            label_for_v2[lbl] += 1
            res = mapper.map(lbl, "is")
            if res.account_code != "is.revenue":
                unmapped[lbl] += 1
                if len(examples) < 20:
                    examples.append((name, fy, basis[:4], lbl, res.account_code, res.stage,
                                     v2rev, v3rev))

        print("=== top labels carrying v2's revenue value (financial corps) ===")
        for lbl, n in label_for_v2.most_common(30):
            res = get_mapper().map(lbl, "is") if not lbl.startswith("<") else None
            tag = f"-> {res.account_code}/{res.stage}" if res else ""
            flag = "  ★NOT is.revenue" if res and res.account_code != "is.revenue" else ""
            print(f"  {n:>4}  {lbl!r:40} {tag}{flag}")

        print(f"\n=== labels the mapper does NOT resolve to is.revenue "
              f"({sum(unmapped.values())} cells, {len(unmapped)} distinct) ===")
        for lbl, n in unmapped.most_common(30):
            res = get_mapper().map(lbl, "is")
            print(f"  {n:>4}  {lbl!r:40} -> {res.account_code}/{res.stage}")

        print("\n=== examples (v2 value's label not mapped to revenue) ===")
        for name, fy, basis, lbl, code, stage, v2rev, v3rev in examples:
            v3s = f"{v3rev:,}" if v3rev is not None else "NULL"
            print(f"  {name:14}{fy} {basis}  {lbl!r:34} ->{code}/{stage}  "
                  f"v2={v2rev:,} v3={v3s}")


if __name__ == "__main__":
    main()
