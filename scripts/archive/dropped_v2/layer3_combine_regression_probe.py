"""Non-mutating regression probe for the min-depth conflict rule + insurance aliases.

Recomputes combine_full in-memory for a sample of corps and compares the fresh output
against the CURRENTLY-STORED std_financials_v3 values (built before the change). For
every metric cell that changes, checks direction against std_financials_v2:

  filled_toward_v2   : NULL -> value, and the new value == v2 (a held conflict resolved
                       correctly). ★the intended win.
  filled_other       : NULL -> value, v2 null or different.
  changed_toward_v2  : value -> different value that now == v2.
  changed_away_v2    : value -> different value, and the OLD value == v2 (★regression!).
  changed_other      : value -> value, neither old nor new == v2.
  emptied            : value -> NULL (★regression — lost a value).

Writes nothing. Run this BEFORE the full rebuild to gate the change.
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
from fin2.layer3.combine import combine_full, build_merged_lines

METRICS = ["total_assets", "total_equity", "retained_earnings", "cash",
           "revenue", "operating_income", "net_income", "cfo"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--corps", type=int, default=200)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fin-all", action="store_true",
                    help="include ALL financial-sector corps (64/65/66) plus the sample")
    args = ap.parse_args()

    kind = Counter()
    regressions = []
    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM std_financials_v3")).fetchall()]
        rnd = random.Random(args.seed)
        rnd.shuffle(corps)
        sample = set(corps[:args.corps])
        if args.fin_all:
            fin = [r[0] for r in s.execute(text("""
                SELECT corp_code FROM corporations
                WHERE induty_code LIKE '64%' OR induty_code LIKE '65%' OR induty_code LIKE '66%'
            """)).fetchall()]
            sample |= set(fin)

        for corp in sample:
            rows = s.execute(text("""
                SELECT fiscal_year, fiscal_period, statement_type, """ + ", ".join(METRICS) + """
                FROM std_financials_v3
                WHERE corp_code=:c AND fiscal_period=:p
            """), {"c": corp, "p": args.period}).fetchall()
            if not rows:
                continue
            # v2 lookup for this corp/period
            v2rows = s.execute(text("""
                SELECT fiscal_year, statement_type, """ + ", ".join(METRICS) + """
                FROM std_financials_v2
                WHERE corp_code=:c AND fiscal_period=:p AND version=1
                  AND NOT is_stub AND NOT is_discrete
            """), {"c": corp, "p": args.period}).fetchall()
            v2map = {(r[0], r[1]): {METRICS[i]: r[2 + i] for i in range(len(METRICS))} for r in v2rows}

            by_fy = {}
            for r in rows:
                by_fy.setdefault(r[0], []).append(r)
            for fy, frows in by_fy.items():
                merged = build_merged_lines(s, corp, fy, args.period)
                if not merged:
                    continue
                for r in frows:
                    basis = r[2]
                    stored = {METRICS[i]: r[3 + i] for i in range(len(METRICS))}
                    col, _, _ = combine_full(s, corp, fy, args.period, basis, merged=merged)
                    v2 = v2map.get((fy, basis), {})
                    for m in METRICS:
                        old = stored[m]
                        new = col.get(m)
                        if old == new:
                            continue
                        v2v = v2.get(m)
                        if old is None and new is not None:
                            if new == 0:
                                kind["filled_zero"] += 1
                                regressions.append(("filled_zero", corp, fy, basis, m, old, new, v2v))
                            else:
                                kind["filled_toward_v2" if new == v2v else "filled_other"] += 1
                        elif old is not None and new is None:
                            kind["emptied"] += 1
                            regressions.append(("emptied", corp, fy, basis, m, old, new, v2v))
                        else:
                            if new == v2v:
                                kind["changed_toward_v2"] += 1
                            elif old == v2v:
                                kind["changed_away_v2"] += 1
                                regressions.append(("away_v2", corp, fy, basis, m, old, new, v2v))
                            else:
                                kind["changed_other"] += 1
                                regressions.append(("other", corp, fy, basis, m, old, new, v2v))

    print(f"Regression probe ({args.period}, {len(sample)} corps, "
          f"{'incl all financial' if args.fin_all else 'random sample'}):\n")
    for k, v in kind.most_common():
        print(f"  {k:<20}{v:>6}")
    good = kind["filled_toward_v2"] + kind["changed_toward_v2"]
    bad = kind["changed_away_v2"] + kind["emptied"]
    print(f"\n  toward-v2 (good) = {good}   away/emptied (regression) = {bad}   "
          f"other = {kind['filled_other'] + kind['changed_other']}")
    print("\n★ potential regressions (away_v2 / emptied / other) — sample:")
    for tag, corp, fy, basis, m, old, new, v2v in regressions[:30]:
        os_ = f"{old:,}" if old is not None else "NULL"
        ns = f"{new:,}" if new is not None else "NULL"
        vs = f"{v2v:,}" if v2v is not None else "NULL"
        print(f"  [{tag}] {corp} {fy} {basis[:4]} {m}: old={os_} new={ns} v2={vs}")


if __name__ == "__main__":
    main()
