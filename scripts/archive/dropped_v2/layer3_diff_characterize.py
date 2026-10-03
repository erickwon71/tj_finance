"""L3-1b DIFF characterizer (READ-ONLY).

After filing selection (select_canonical_rcept), the residual DIFF = combine value
≠ std_v2 value. Classify each DIFF by whether our canonical filing differs from the
filing std_v2 used:

  RCEPT_DIFF   : our is_final rcept ≠ std_v2's bs_rcept → filing-selection edge
                 (e.g. 소급재작성: std kept original, is_final is a late amendment).
                 Not an engine bug — a filing-selection policy question.
  SAME_RCEPT   : same filing but value differs → genuine engine/label disagreement
                 (e.g. total vs sub-line pick). These are the ones to inspect.

Writes nothing to the DB.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.layer3.combine import combine, collect_candidates, select_canonical_rcept

TARGETS = [
    ("is.revenue", "revenue"), ("is.operating_income", "operating_income"),
    ("is.net_income", "net_income"), ("bs.total_assets", "total_assets"),
    ("bs.total_equity", "total_equity"), ("bs.retained_earnings", "retained_earnings"),
]
STD_COLS = [c[1] for c in TARGETS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=400)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--show-same", type=int, default=8, help="how many SAME_RCEPT to print")
    args = ap.parse_args()

    kind = Counter()
    same_examples = []
    cols = ", ".join(STD_COLS)

    with get_session() as s:
        not_null = " OR ".join(f"{c} IS NOT NULL" for c in STD_COLS)
        rows = s.execute(text(f"""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type,
                   {cols}, bs_rcept, is_rcept
            FROM std_financials_v2
            WHERE fiscal_year >= 2015 AND fiscal_period = :p
              AND version=1 AND NOT is_stub AND NOT is_discrete AND ({not_null})
        """), {"p": args.period}).fetchall()
        rnd = random.Random(args.seed)
        rnd.shuffle(rows)
        keys = rows[:args.sample]
        nc = len(STD_COLS)

        for row in keys:
            corp, fy, period, stmt_type = row[0], row[1], row[2], row[3]
            svals = {STD_COLS[i]: row[4 + i] for i in range(nc)}
            std_bs_rcept, std_is_rcept = row[4 + nc], row[5 + nc]
            our_rcept = select_canonical_rcept(s, corp, fy, period)
            col, _ = combine(s, corp, fy, period, stmt_type)

            for canonical, std_col in TARGETS:
                std_v = svals.get(std_col)
                if std_v is None or std_col not in col:
                    continue
                if col[std_col] == int(std_v):
                    continue
                # DIFF: compare filing identity (BS metrics vs bs_rcept, IS vs is_rcept)
                std_rcept = std_bs_rcept if canonical.startswith("bs.") else std_is_rcept
                if our_rcept != std_rcept:
                    kind["RCEPT_DIFF"] += 1
                else:
                    kind["SAME_RCEPT"] += 1
                    if len(same_examples) < args.show_same:
                        # show candidates from the SELECTED canonical filing (what
                        # combine actually saw) — NOT pooled across all filings.
                        rbs = {"BS": our_rcept, "IS": our_rcept, "CF": our_rcept}
                        cands = collect_candidates(s, corp, fy, period, stmt_type,
                                                   rcept_by_stmt=rbs)
                        same_examples.append(
                            (canonical, corp, fy, stmt_type, col[std_col], int(std_v),
                             our_rcept, cands.get(canonical, [])))

    print("DIFF classification (after L3-1b filing selection):")
    for k, v in kind.most_common():
        print(f"  {k:<12}{v:>5}")
    print("\nSAME_RCEPT examples (same filing, value differs — inspect these):")
    for canonical, corp, fy, t, chosen, sv, rcept, cands in same_examples:
        print(f"\n  {canonical} {corp} {fy} {t}  rcept={rcept}")
        print(f"    combine={chosen:,}  std={sv:,}")
        for r in cands:
            print(f"      val={r['value']:>18,}  stage={r['stage']:<10} role={r['node_role']} "
                  f"path={r['section_path']}  label={r['label_raw']!r}")


if __name__ == "__main__":
    main()
