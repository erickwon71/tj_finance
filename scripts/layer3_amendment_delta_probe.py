"""L3-1b amendment-delta probe (READ-ONLY, measure-first).

The chosen policy (user, 2026-07-22): keep the ORIGINAL filing as the base and
apply only the actually-changed/added cells from each 기재정정 (amendment), in
order, marking amended cells with their source rcept. Before implementing the
delta-patch we must measure how cleanly cells align between original and
amendment, and what the delta looks like.

Candidate cell key: (statement, basis, col_index, section_path, label_raw).
For each original↔amendment pair (both present in report_lines), classify cells:
  SAME       : key in both, equal value_won
  CHANGED    : key in both, different value  (amendment edits)
  ONLY_ORIG  : key only in original          (dropped / restructured)
  ONLY_AMEND : key only in amendment         (added)

Prints aggregate shape + a few CHANGED/ONLY examples so we can judge whether the
key is stable enough for cell-level patching. Writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session

CELL_COLS = "statement, basis, col_index, section_path, label_raw"


def find_amendment_pairs(session, limit, year_min):
    """(corp, fy, period, original_rcept, amendment_rcept) where BOTH have report_lines.
    original = earliest filed; amendment = a later is_amendment filing."""
    return session.execute(text("""
        WITH cand AS (
          SELECT f.corp_code, f.fiscal_year, f.fiscal_period, f.rcept_no,
                 f.filed_at, f.is_amendment,
                 EXISTS(SELECT 1 FROM report_lines rl WHERE rl.rcept_no=f.rcept_no) has_rl
          FROM filings f
          WHERE f.fiscal_year>=:ym AND f.fiscal_period='FY'
        )
        SELECT o.corp_code, o.fiscal_year, o.fiscal_period, o.rcept_no AS orig, a.rcept_no AS amend
        FROM cand o
        JOIN cand a ON a.corp_code=o.corp_code AND a.fiscal_year=o.fiscal_year
                   AND a.fiscal_period=o.fiscal_period AND a.filed_at>o.filed_at
        WHERE o.has_rl AND a.has_rl AND a.is_amendment
          AND o.filed_at = (SELECT min(filed_at) FROM cand c
                            WHERE c.corp_code=o.corp_code AND c.fiscal_year=o.fiscal_year
                              AND c.fiscal_period=o.fiscal_period AND c.has_rl)
        ORDER BY o.corp_code, a.rcept_no
        LIMIT :lim
    """), {"ym": year_min, "lim": limit}).fetchall()


def cells(session, rcept):
    rows = session.execute(text(f"""
        SELECT {CELL_COLS}, value_won FROM report_lines
        WHERE rcept_no=:r AND col_index=0
    """), {"r": rcept}).fetchall()
    d = {}
    for row in rows:
        key = tuple(row[:5])
        d[key] = row[5]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--pairs", type=int, default=60)
    ap.add_argument("--year-min", type=int, default=2015)
    ap.add_argument("--examples", type=int, default=6)
    args = ap.parse_args()

    agg = Counter()
    pair_shapes = Counter()   # how many pairs are pure-same / have-changes / etc.
    examples = []

    with get_session() as s:
        pairs = find_amendment_pairs(s, args.pairs, args.year_min)
        print(f"amendment pairs (both in report_lines, {args.year_min}+ FY): {len(pairs)}\n")
        for corp, fy, period, orig, amend in pairs:
            oc = cells(s, orig)
            ac = cells(s, amend)
            okeys, akeys = set(oc), set(ac)
            same = changed = 0
            ch_ex = []
            for k in okeys & akeys:
                if oc[k] == ac[k]:
                    same += 1
                else:
                    changed += 1
                    ch_ex.append((k, oc[k], ac[k]))
            only_o = len(okeys - akeys)
            only_a = len(akeys - okeys)
            agg["SAME"] += same
            agg["CHANGED"] += changed
            agg["ONLY_ORIG"] += only_o
            agg["ONLY_AMEND"] += only_a

            if changed == 0 and only_o == 0 and only_a == 0:
                pair_shapes["identical"] += 1
            elif changed > 0 and only_o == 0 and only_a == 0:
                pair_shapes["value_edits_only"] += 1
            elif changed == 0 and (only_o or only_a):
                pair_shapes["structure_only"] += 1
            else:
                pair_shapes["mixed"] += 1

            if ch_ex and len(examples) < args.examples:
                examples.append((corp, fy, orig, amend, changed, only_o, only_a, ch_ex[:4]))

    print("=== aggregate cell classification (all pairs) ===")
    tot = sum(agg.values()) or 1
    for k in ("SAME", "CHANGED", "ONLY_ORIG", "ONLY_AMEND"):
        print(f"  {k:<12}{agg[k]:>8}  ({100.0*agg[k]/tot:5.1f}%)")
    print("\n=== per-pair shape ===")
    for k, v in pair_shapes.most_common():
        print(f"  {k:<18}{v:>5}")
    print("\n=== CHANGED examples (key: statement/basis/col/path/label  orig→amend) ===")
    for corp, fy, orig, amend, ch, oo, oa, exs in examples:
        print(f"\n  {corp} {fy}  orig={orig} amend={amend}  changed={ch} only_orig={oo} only_amend={oa}")
        for k, ov, av in exs:
            stmt, basis, col, path, label = k
            print(f"      [{stmt}/{basis}] {label!r} ({path})")
            print(f"          {ov:,} → {av:,}")


if __name__ == "__main__":
    main()
