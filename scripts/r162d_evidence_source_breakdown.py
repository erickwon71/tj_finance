#!/usr/bin/env python
"""For each R162-d dual-evidence candidate cell, classify WHERE its negative-magnitude
evidence actually lives: same basis/same statement (SCE, other row) vs the OPPOSITE
basis's SCE (cross-basis leakage — suspect, since separate and consolidated OCI/equity
lines can legitimately differ in sign) vs another statement (BS/IS/CF, same basis —
a real anchor) vs note_lines.

Motivation: manual check of the first sample (20171114002176/separate row_order=2)
showed the DB's "evidence" was the SAME magnitude from the CONSOLIDATED SCE table,
while the raw XML for the SEPARATE table shows BOTH involved cells printed positive,
no parens, and mutually consistent — i.e. that candidate is a false positive caused by
an EARLIER rule (R162) having already wrongly flipped one sibling cell, which R162-d
then "confirms" via cross-basis coincidence. This script measures how common that
evidence pattern is across all candidates.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

CAND_PATH = Path("docs/qa/r162d_dual_evidence_candidates_2026-09-25.jsonl")


def main() -> int:
    cands = [json.loads(l) for l in CAND_PATH.open(encoding="utf-8")]
    by_rcept = defaultdict(list)
    for c in cands:
        by_rcept[c["rcept_no"]].append(c)
    rcepts = list(by_rcept)
    print("candidates: %d cells / %d filings" % (len(cands), len(rcepts)))

    site_counts = Counter()          # per-cell evidence-site classification
    with get_session() as s:
        for i in range(0, len(rcepts), 500):
            chunk = rcepts[i:i + 500]
            rows = s.execute(text(
                "SELECT rcept_no, statement, basis, table_seq, row_order, value_won "
                "FROM report_lines WHERE value_won < 0 AND rcept_no = ANY(:r)"),
                {"r": chunk}).mappings().all()
            # (rcept, abs(val)) -> [(statement, basis, table_seq, row_order), ...]
            neg_index = defaultdict(list)
            for r in rows:
                neg_index[(r["rcept_no"], -int(r["value_won"]))].append(
                    (r["statement"], r["basis"], r["table_seq"], r["row_order"]))
            note_rows = s.execute(text(
                "SELECT rcept_no, value_won FROM note_lines "
                "WHERE value_won < 0 AND rcept_no = ANY(:r)"),
                {"r": chunk}).mappings().all()
            note_index = defaultdict(int)
            for r in note_rows:
                note_index[(r["rcept_no"], -int(r["value_won"]))] += 1

            for rcept in chunk:
                for c in by_rcept[rcept]:
                    mag = abs(int(c["value_won"]))
                    row_site = ("SCE", c["basis"], c["table_seq"], c["row_order"])
                    sites_full = neg_index.get((rcept, mag), [])
                    sites = [(st, b) for st, b, ts, ro in sites_full
                             if (st, b, ts, ro) != row_site]
                    has_note = note_index.get((rcept, mag), 0) > 0
                    same_basis_sce = any(st == "SCE" and b == c["basis"] for st, b in sites)
                    cross_basis_sce = any(st == "SCE" and b != c["basis"] for st, b in sites)
                    other_stmt_same_basis = any(st != "SCE" and b == c["basis"] for st, b in sites)
                    other_stmt_cross_basis = any(st != "SCE" and b != c["basis"] for st, b in sites)
                    # priority for a single label per cell: prefer the "strongest" anchor type
                    if other_stmt_same_basis:
                        site_counts["A: same-basis BS/IS/CF anchor"] += 1
                    elif same_basis_sce:
                        site_counts["B: same-basis, other SCE row"] += 1
                    elif other_stmt_cross_basis:
                        site_counts["C: opposite-basis BS/IS/CF"] += 1
                    elif cross_basis_sce:
                        site_counts["D: opposite-basis SCE only (suspect)"] += 1
                    elif has_note:
                        site_counts["E: note_lines only"] += 1
                    else:
                        site_counts["F: unclassified"] += 1
            print("  ... %d/%d filings classified" % (min(i + 500, len(rcepts)), len(rcepts)), flush=True)

    print("\nevidence-site breakdown (cells):")
    total = sum(site_counts.values())
    for k in sorted(site_counts):
        n = site_counts[k]
        print("  %-42s %6d  (%.1f%%)" % (k, n, 100.0 * n / total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
