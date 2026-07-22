"""L3-1 combine-engine probe (READ-ONLY).

Runs fin2.layer3.combine against a std_v2 sample and measures MATCH/DIFF/
CONFLICT/MISSING per metric — the successor to layer3_label_norm_probe.py, which
had NO conflict resolution. The point is to see how much the ported _resolve
(strictest-stage + _reduce_conflict) converts the plain probe's CONFLICTs into
MATCH, and to dump residual conflicts (with node_role / section_path) as evidence
for a node_role-based rule.

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
from fin2.layer3.combine import combine, collect_candidates

# canonical -> (std_v2 column)
TARGETS = [
    ("is.revenue",           "revenue"),
    ("is.operating_income",  "operating_income"),
    ("is.net_income",        "net_income"),
    ("bs.total_assets",      "total_assets"),
    ("bs.total_equity",      "total_equity"),
    ("bs.retained_earnings", "retained_earnings"),
]
STD_COLS = [c[1] for c in TARGETS]


def sample_keys(session, n, period, seed):
    not_null = " OR ".join(f"{c} IS NOT NULL" for c in STD_COLS)
    rows = session.execute(text(f"""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type
        FROM std_financials_v2
        WHERE fiscal_year >= 2015 AND fiscal_period = :p
          AND version=1 AND NOT is_stub AND NOT is_discrete AND ({not_null})
    """), {"p": period}).fetchall()
    rnd = random.Random(seed)
    rnd.shuffle(rows)
    return rows[:n]


def std_values(session, corp, fy, period, stmt_type):
    cols = ", ".join(STD_COLS)
    row = session.execute(text(f"""
        SELECT {cols} FROM std_financials_v2
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
          AND statement_type=:t AND version=1 AND NOT is_stub AND NOT is_discrete LIMIT 1
    """), {"c": corp, "y": fy, "p": period, "t": stmt_type}).fetchone()
    return {STD_COLS[i]: row[i] for i in range(len(STD_COLS))} if row else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=400)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dump", default="", help="canonical to dump residual conflicts for")
    args = ap.parse_args()

    stat = {c[0]: Counter() for c in TARGETS}
    dump_rows = []

    with get_session() as s:
        keys = sample_keys(s, args.sample, args.period, args.seed)
        print(f"sampled {len(keys)} std_v2 filings ({args.period}, year>=2015)\n")

        for corp, fy, period, stmt_type in keys:
            svals = std_values(s, corp, fy, period, stmt_type)
            col, conflicts = combine(s, corp, fy, period, stmt_type)

            for canonical, std_col in TARGETS:
                std_v = svals.get(std_col)
                if std_v is None:
                    stat[canonical]["NO_STD"] += 1
                    continue
                outcome = None
                if std_col in col:
                    outcome = "MATCH" if col[std_col] == int(std_v) else "DIFF"
                elif canonical in conflicts:
                    outcome = "CONFLICT"
                else:
                    outcome = "MISSING"
                stat[canonical][outcome] += 1

                if (args.dump and canonical == args.dump
                        and outcome in ("DIFF", "CONFLICT") and len(dump_rows) < 14):
                    cands = collect_candidates(s, corp, fy, period, stmt_type)
                    dump_rows.append((corp, fy, stmt_type, outcome,
                                      col.get(std_col), int(std_v),
                                      cands.get(canonical, [])))

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

    if args.dump and dump_rows:
        print(f"\nDIFF/CONFLICT for {args.dump} (chosen vs std + all candidates):")
        for corp, fy, t, outcome, chosen, sv, cands in dump_rows:
            ch = f"{chosen:,}" if chosen is not None else "None(held)"
            print(f"\n  [{outcome}] {corp} {fy} {t}  chosen={ch}  std={sv:,}")
            for r in cands:
                print(f"      val={r['value']:>18,}  stage={r['stage']:<10} "
                      f"role={r['node_role']}  path={r['section_path']}  "
                      f"label={r['label_raw']!r}")


if __name__ == "__main__":
    main()
