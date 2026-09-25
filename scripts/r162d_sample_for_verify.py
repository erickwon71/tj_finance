#!/usr/bin/env python
"""Pick a small stratified sample of R162-d candidates (by evidence-site category)
with full detail (own row + the evidence row it matched against) for manual
source verification. Writes one JSON record per sample line.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

CAND_PATH = Path("docs/qa/r162d_dual_evidence_candidates_2026-09-25.jsonl")
N_PER_CAT = 5
SEED = 20260925


def classify(c, sites, has_note):
    same_basis_sce = [s for s in sites if s[0] == "SCE" and s[1] == c["basis"]]
    other_stmt_same_basis = [s for s in sites if s[0] != "SCE" and s[1] == c["basis"]]
    other_stmt_cross_basis = [s for s in sites if s[0] != "SCE" and s[1] != c["basis"]]
    cross_basis_sce = [s for s in sites if s[0] == "SCE" and s[1] != c["basis"]]
    if other_stmt_same_basis:
        return "A", other_stmt_same_basis
    if same_basis_sce:
        return "B", same_basis_sce
    if other_stmt_cross_basis:
        return "C", other_stmt_cross_basis
    if cross_basis_sce:
        return "D", cross_basis_sce
    if has_note:
        return "E", []
    return "F", []


def main() -> int:
    cands = [json.loads(l) for l in CAND_PATH.open(encoding="utf-8")]
    by_rcept = defaultdict(list)
    for c in cands:
        by_rcept[c["rcept_no"]].append(c)
    rcepts = list(by_rcept)

    buckets = defaultdict(list)
    with get_session() as s:
        for i in range(0, len(rcepts), 500):
            chunk = rcepts[i:i + 500]
            rows = s.execute(text(
                "SELECT rcept_no, statement, basis, table_seq, row_order, label_raw, value_won "
                "FROM report_lines WHERE value_won < 0 AND rcept_no = ANY(:r)"),
                {"r": chunk}).mappings().all()
            neg_index = defaultdict(list)
            for r in rows:
                neg_index[(r["rcept_no"], -int(r["value_won"]))].append(
                    (r["statement"], r["basis"], r["table_seq"], r["row_order"], r["label_raw"]))
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
                    sites = [(st, b, ro, lb) for st, b, ts, ro, lb in sites_full
                             if (st, b, ts, ro) != row_site]
                    has_note = note_index.get((rcept, mag), 0) > 0
                    cat, evid = classify(c, sites, has_note)
                    buckets[cat].append((c, evid))

    print({k: len(v) for k, v in buckets.items()})
    rng = random.Random(SEED)
    sample = []
    for cat in "ABCDE":
        items = buckets.get(cat, [])
        rng.shuffle(items)
        for c, evid in items[:N_PER_CAT]:
            sample.append({"category": cat, "candidate": c, "evidence_rows": evid[:3]})

    out = Path("docs/qa/r162d_manual_verify_sample_2026-09-25.jsonl")
    with out.open("w", encoding="utf-8") as fh:
        for rec in sample:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote %d samples -> %s" % (len(sample), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
