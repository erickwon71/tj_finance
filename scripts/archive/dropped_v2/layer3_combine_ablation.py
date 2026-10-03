"""L3-1 ablation (READ-ONLY): does the combine engine reproduce std_v2 when given
the SAME source filing the old chain used?

The plain combine probe pools ALL filings for a period (original + amendments +
restatements), which produces spurious conflicts because Layer-2 pass-4 (정본
선택 / filing selection) has not run yet. Here we feed the engine std_v2's own
bs_rcept / is_rcept so BOTH chains read the identical filing. If conflicts
collapse and match→~100%, the combine engine is sound and the remaining work is
purely filing selection (independent of the label/resolution engine).

Writes nothing to the DB.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.layer3.combine import combine

TARGETS = [
    ("is.revenue", "revenue"), ("is.operating_income", "operating_income"),
    ("is.net_income", "net_income"), ("bs.total_assets", "total_assets"),
    ("bs.total_equity", "total_equity"), ("bs.retained_earnings", "retained_earnings"),
]
STD_COLS = [c[1] for c in TARGETS]
# which filing feeds each statement
_RCEPT_STMT = {"BS": "bs_rcept", "IS": "is_rcept"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=400)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    stat = {c[0]: Counter() for c in TARGETS}
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
        print(f"sampled {len(keys)} std_v2 filings; feeding engine std's bs/is_rcept\n")

        nc = len(STD_COLS)
        for row in keys:
            corp, fy, period, stmt_type = row[0], row[1], row[2], row[3]
            svals = {STD_COLS[i]: row[4 + i] for i in range(nc)}
            bs_rcept, is_rcept = row[4 + nc], row[5 + nc]
            rcept_by_stmt = {"BS": bs_rcept, "IS": is_rcept}
            col, conflicts = combine(s, corp, fy, period, stmt_type,
                                     rcept_by_stmt=rcept_by_stmt)
            for canonical, std_col in TARGETS:
                std_v = svals.get(std_col)
                if std_v is None:
                    stat[canonical]["NO_STD"] += 1
                elif std_col in col:
                    stat[canonical]["MATCH" if col[std_col] == int(std_v) else "DIFF"] += 1
                elif canonical in conflicts:
                    stat[canonical]["CONFLICT"] += 1
                else:
                    stat[canonical]["MISSING"] += 1

    print("=" * 82)
    print(f"{'metric':<22}{'N':>6}{'MATCH':>8}{'DIFF':>7}{'CONFL':>7}{'MISS':>7}{'match%':>9}")
    print("-" * 82)
    for canonical, _ in TARGETS:
        c = stat[canonical]
        n = c["MATCH"] + c["DIFF"] + c["CONFLICT"] + c["MISSING"]
        pct = (100.0 * c["MATCH"] / n) if n else 0.0
        print(f"{canonical:<22}{n:>6}{c['MATCH']:>8}{c['DIFF']:>7}"
              f"{c['CONFLICT']:>7}{c['MISSING']:>7}{pct:>8.1f}%")
    print("=" * 82)


if __name__ == "__main__":
    main()
