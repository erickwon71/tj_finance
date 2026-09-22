#!/usr/bin/env python
"""R162-d candidate scan - the SCE's own WITHIN-ROW identity as a sign anchor.

    지배기업 소유주지분 + 비지배지분 = 자본 합계

R162 anchors on the column roll-forward identity (기초 + Sum(변동) = 기말) plus a
BS/IS cross-reference, so it reaches only cells that a period boundary or an
external statement can pin down. Prior-year balance rows have neither - which
is why Hanwha Ocean r20160330004251 had 1 of 4 cells repaired (camp_run's
observation, 2026-09-22).

This identity is different and STRONGER for a single cell: within one row, if
the owners' share and the total are known, 비지배지분 is DETERMINED
(= total - owners). There is no mirror ambiguity, unlike the column identity
where negating every sign satisfies it equally.

★This script only produces CANDIDATES and the evidence for each. It writes
nothing. Per the user's decision (2026-09-22) the backfill is a separate call.

## Why candidates and not defects

Two ways this can be wrong, both guarded here:

  1. Column mis-mapping. Picking the wrong physical column for owners/nci/total
     breaks the identity for reasons that have nothing to do with signs. So a
     candidate must have EXACTLY ONE column matching each of the three roles -
     ambiguous rows are reported separately, never repaired.
  2. The wrong cell is to blame. If the owners' cell lost its sign instead, the
     derived 비지배지분 would be wrong. So a candidate must be closed by
     flipping exactly ONE of the three cells; rows where two different single
     flips both close it are reported as ambiguous.

Usage:
    python scripts/scan_r162d_row_identity.py
    python scripts/scan_r162d_row_identity.py --out <path> --detail 40
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_CELLS_SQL = """
SELECT rcept_no, basis, row_order, label_raw, col_index, col_label, value_won
FROM report_lines
WHERE statement = 'SCE' AND report_fiscal_year >= 2015
  AND col_label IS NOT NULL AND value_won IS NOT NULL
"""


def concept(col_label: str) -> str:
    """'자본>비지배지분' -> '비지배지분' (the same convention R162 uses)."""
    return (col_label or "").split(">")[-1].strip()


def _roles(cols: dict) -> tuple:
    """Classify columns into (owners, nci, total); each must be UNAMBIGUOUS.

    Returns (owners, nci, total, ambiguous) where each of the first three is
    (concept, col_index, value) or None.
    """
    owners, nci, total = [], [], []
    for (name, ci), v in cols.items():
        flat = name.replace(" ", "")
        if "비지배" in flat:
            nci.append((name, ci, v))
        elif "귀속" in flat or "지배기업" in flat or "지배주주" in flat:
            owners.append((name, ci, v))
        elif flat.endswith("합계") or flat.endswith("총계"):
            total.append((name, ci, v))
    ambiguous = len(owners) > 1 or len(nci) > 1 or len(total) > 1
    return (owners[0] if len(owners) == 1 else None,
            nci[0] if len(nci) == 1 else None,
            total[0] if len(total) == 1 else None,
            ambiguous)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write candidate filing list here")
    ap.add_argument("--detail", type=int, default=25)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(_CELLS_SQL)).mappings().all()
    print("SCE cells scanned: %d" % len(rows))

    by_row: dict = defaultdict(dict)
    for r in rows:
        key = (r["rcept_no"], r["basis"], r["row_order"], r["label_raw"])
        by_row[key][(concept(r["col_label"]), r["col_index"])] = r["value_won"]

    n_eligible = 0
    n_holds = 0
    n_ambiguous_cols = 0
    n_multi_flip = 0
    n_unexplained = 0
    cand: dict = defaultdict(list)          # role -> [(key, value)]
    detail: list = []

    for key, cols in by_row.items():
        owners, nci, total, amb = _roles(cols)
        if owners is None or nci is None or total is None:
            if amb:
                n_ambiguous_cols += 1
            continue
        n_eligible += 1
        o, n, t = owners[2], nci[2], total[2]
        if o + n == t:
            n_holds += 1
            continue

        # Which single flip closes it? Collect ALL that do.
        closers = []
        if o - n == t and n > 0:
            closers.append(("nci", nci))
        if n - o == t and o > 0:
            closers.append(("owners", owners))
        if o + n == -t and t > 0:
            closers.append(("total", total))
        if len(closers) == 1:
            role, cell = closers[0]
            cand[role].append((key, cell))
            if len(detail) < args.detail:
                detail.append((key, role, owners, nci, total))
        elif len(closers) > 1:
            n_multi_flip += 1
        else:
            n_unexplained += 1

    print("\nrows with an unambiguous (owners, nci, total) triple : %d" % n_eligible)
    print("  identity already holds                             : %d" % n_holds)
    print("  ★closed by flipping exactly ONE cell               : %d"
          % sum(len(v) for v in cand.values()))
    for role in sorted(cand):
        filings = {k[0] for k, _c in cand[role]}
        print("      %-7s %6d cell(s)  %5d filing(s)"
              % (role, len(cand[role]), len(filings)))
    print("  two different single flips both close it (skip)    : %d" % n_multi_flip)
    print("  broken, no single flip closes it (skip)            : %d" % n_unexplained)
    print("\nrows skipped for ambiguous column roles             : %d"
          % n_ambiguous_cols)

    if detail:
        print("\nevidence sample (owners / nci / total as loaded):")
        for key, role, owners, nci, total in detail:
            rcept, basis, ro, label = key
            print("  %s %-13s row=%-4s %-22s  flip=%s" % (
                rcept, basis, ro, (label or "")[:22], role))
            for nm, cell in (("owners", owners), ("nci", nci), ("total", total)):
                print("      %-7s col=%-3s %-28s %22s" % (
                    nm, cell[1], cell[0][:28], "{:,}".format(cell[2])))

    all_filings = sorted({k[0] for v in cand.values() for k, _c in v})
    if args.out and all_filings:
        Path(args.out).write_text("\n".join(all_filings) + "\n")
        print("\ncandidate filings -> %s (%d)" % (args.out, len(all_filings)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
