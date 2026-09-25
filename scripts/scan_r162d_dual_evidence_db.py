#!/usr/bin/env python
"""R162-d candidate scan (DB-based, evidence-aware) — reproduces the row-identity +
dual-evidence logic staged in `docs/qa/r162d_row_identity_WIP_2026-09-25.diff`
(`fin2.extract.sce_sign_repair.repair_sce_row_identity`) but reads straight from
`report_lines` instead of a live extraction pass.

★This is a CANDIDATE FINDER for sampling only — it does not write anything, and
it is NOT idempotent with a re-extraction (the handoff doc's caveat: the DB row
set at load time can differ from what a fresh parse produces). Use it to pick a
stratified sample for source verification; measure real scale/accuracy only by
comparing re-extraction runs.

Identity (col_label hierarchy, per parent path):
    one 'total'-like child (합계/총계) + N sibling children -> Sigma(children) = total
    (recurses: a sibling that is itself a group contributes via its own total)

Candidate = a row where >=1 identity is broken, closed by negating a UNIQUE
minimal subset (size 1..3) of the row's POSITIVE cells without breaking any
identity that already held.

Dual evidence (per flipped cell, per user decision 2026-09-25): the same
magnitude must appear as a NEGATIVE value somewhere else in the same filing —
in report_lines (any statement/table/row, excluding the row itself) or in
note_lines.

Usage:
    python scripts/scan_r162d_dual_evidence_db.py --out docs/qa/r162d_dual_evidence_candidates_2026-09-25.jsonl
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_TOTAL_COL_RE = re.compile(r"합\s*계|총\s*계")
_MAX_ROW_FLIP = 3

_SCE_SQL = """
SELECT rcept_no, basis, table_seq, row_order, label_raw, col_index, col_label, value_won
FROM report_lines
WHERE statement = 'SCE' AND report_fiscal_year >= 2015
  AND col_label IS NOT NULL AND value_won IS NOT NULL
ORDER BY rcept_no, basis, table_seq, row_order
"""


def _identities(by_path: dict) -> list:
    children = defaultdict(list)
    for path in by_path:
        children[path[:-1]].append(path)
    out = []
    for parent, kids in children.items():
        totals = [k for k in kids if _TOTAL_COL_RE.search(k[-1])]
        if len(totals) != 1:
            continue
        members = [k for k in kids if k != totals[0]]
        resolved = []
        groups = {k[:len(parent) + 1] for k in by_path if len(k) > len(parent) + 1
                  and k[:len(parent)] == parent}
        ok = True
        for m in members:
            if m in by_path:
                resolved.append(m)
        for g in groups:
            gkids = children.get(g, [])
            gt = [k for k in gkids if _TOTAL_COL_RE.search(k[-1])]
            if len(gt) != 1:
                ok = False
                break
            resolved.append(gt[0])
        if ok and resolved:
            out.append((totals[0], resolved))
    return out


def _find_row_candidates(cells: list) -> list:
    """Returns list of (solution_paths, by_path, identity_participants) for one
    (rcept,basis,table_seq,row_order) row.

    `identity_participants[p]` = the set of column paths that co-occur with `p` in
    ANY identity `p` takes part in (as total or member). A sibling cell OUTSIDE that
    set is independent evidence even if it sits in the same physical row (e.g. a
    nested hierarchy's already-correct inner total is real support for the OUTER
    identity, not circular reuse of the identity being solved) — a blanket
    same-row exclusion was over-broad and mis-bucketed many valid single-row-proof
    candidates as "cross-basis only / suspect" (found 2026-09-25 while manually
    verifying samples against raw XML)."""
    by_path = {}
    for c in cells:
        path = tuple(s.strip() for s in c["col_label"].split(">"))
        if path in by_path:
            return []                                  # duplicate column path — ambiguous layout
        by_path[path] = c
    identities = _identities(by_path)
    if not identities:
        return []

    def holds(signs, ident):
        total, members = ident
        val = lambda p: signs.get(p, 1) * by_path[p]["value_won"]  # noqa: E731
        return sum(val(m) for m in members) == val(total)

    base = {}
    broken = [i for i in identities if not holds(base, i)]
    if not broken:
        return []
    involved = sorted({p for t, ms in broken for p in [t, *ms]}
                      | {p for t, ms in identities for p in [t, *ms]})
    positives = [p for p in involved if by_path[p]["value_won"] > 0]
    for size in range(1, _MAX_ROW_FLIP + 1):
        sols = []
        for combo in itertools.combinations(positives, size):
            signs = {p: -1 for p in combo}
            if all(holds(signs, i) for i in identities):
                sols.append(combo)
                if len(sols) > 1:
                    break
        if sols:
            if len(sols) != 1:
                return []
            solution = sols[0]
            participants: Dict[Tuple, Set[Tuple]] = defaultdict(set)
            for t, ms in identities:
                group = {t, *ms}
                for p in group:
                    participants[p] |= group - {p}
            return [(solution, by_path, participants)]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # (rcept_no, basis, table_seq, row_order) -> [(cell_dict, excluded_paths), ...]
    no_evidence_candidates = []
    n_rows_seen = 0
    n_scanned = 0
    with get_session() as s:
        conn = s.connection(execution_options={"stream_results": True})
        print("streaming SCE report_lines ...", flush=True)
        result = conn.execute(text(_SCE_SQL))
        cur_key = None
        cur_cells: list = []

        def flush_group():
            nonlocal n_scanned
            if not cur_cells:
                return
            n_scanned += 1
            for solution, by_path, participants in _find_row_candidates(cur_cells):
                cells = [(by_path[p], participants.get(p, set())) for p in solution]
                no_evidence_candidates.append((cur_key, cells))

        for r in result.mappings():
            n_rows_seen += 1
            key = (r["rcept_no"], r["basis"], r["table_seq"], r["row_order"])
            if key != cur_key:
                flush_group()
                cur_key = key
                cur_cells = []
            cur_cells.append(dict(r))
            if n_rows_seen % 2_000_000 == 0:
                print("  ... %d rows streamed" % n_rows_seen, flush=True)
        flush_group()
        print("SCE eligible rows streamed: %d (rows/groups: %d)" % (n_rows_seen, n_scanned), flush=True)

        cand_filings = {k[0] for k, _ in no_evidence_candidates}
        n_cells_raw = sum(len(cs) for _, cs in no_evidence_candidates)
        print("candidates (evidence ignored): %d filings / %d cells"
              % (len(cand_filings), n_cells_raw), flush=True)

        print("loading negative-value evidence sites (report_lines + note_lines) ...", flush=True)
        # site = (statement, basis, table_seq, row_order, col_path). Excluding only
        # the exact column(s) that participate in the SAME identity as the flipped
        # cell — not the whole physical row — because a nested hierarchy's already-
        # correct inner-level total is real, independent support for an OUTER
        # identity, not circular reuse of the identity being solved (found while
        # manually verifying candidates against raw XML, 2026-09-25: a blanket
        # same-row exclusion mis-bucketed many valid single-row proofs as
        # "cross-basis only / suspect").
        neg_sites_by_rcept = defaultdict(lambda: defaultdict(set))   # rcept -> mag -> {site}
        for r in s.execute(text(
                "SELECT rcept_no, statement, basis, table_seq, row_order, col_label, value_won "
                "FROM report_lines WHERE value_won < 0 AND rcept_no = ANY(:r)"),
                {"r": list(cand_filings)}).mappings():
            col_path = tuple(x.strip() for x in (r["col_label"] or "").split(">"))
            site = (r["statement"], r["basis"], r["table_seq"], r["row_order"], col_path)
            neg_sites_by_rcept[r["rcept_no"]][-int(r["value_won"])].add(site)
        note_neg_by_rcept = defaultdict(set)
        for r in s.execute(text(
                "SELECT rcept_no, value_won FROM note_lines "
                "WHERE value_won < 0 AND rcept_no = ANY(:r)"),
                {"r": list(cand_filings)}).mappings():
            note_neg_by_rcept[r["rcept_no"]].add(-int(r["value_won"]))

    out_path = Path(args.out)
    n_dual = 0
    n_dual_filings = set()
    with out_path.open("w", encoding="utf-8") as fh:
        for key, sol_cells in no_evidence_candidates:
            rcept, basis, table_seq, row_order = key
            all_ok = True
            for c, excluded_paths in sol_cells:
                mag = abs(int(c["value_won"]))
                sites = neg_sites_by_rcept.get(rcept, {}).get(mag, set())
                excluded_sites = {("SCE", basis, table_seq, row_order, p) for p in excluded_paths}
                has_report_evidence = any(s for s in sites if s not in excluded_sites)
                has_note_evidence = mag in note_neg_by_rcept.get(rcept, set())
                if not (has_report_evidence or has_note_evidence):
                    all_ok = False
                    break
            if not all_ok:
                continue                              # ALL flipped cells need evidence (user decision)
            n_dual += len(sol_cells)
            n_dual_filings.add(rcept)
            for c, excluded_paths in sol_cells:
                mag = abs(int(c["value_won"]))
                excluded_sites = {("SCE", basis, table_seq, row_order, p) for p in excluded_paths}
                sites = sorted(s for s in neg_sites_by_rcept.get(rcept, {}).get(mag, set())
                               if s not in excluded_sites)
                rec = {
                    "rcept_no": c["rcept_no"], "basis": c["basis"], "table_seq": c["table_seq"],
                    "row_order": c["row_order"], "label_raw": c["label_raw"],
                    "col_index": c["col_index"], "col_label": c["col_label"],
                    "value_won": c["value_won"], "row_flip_size": len(sol_cells),
                    "evidence_sites": sites,
                    "evidence_note_only": bool(mag in note_neg_by_rcept.get(rcept, set()) and not sites),
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\ndual-evidence candidates: %d filings / %d cells -> %s"
          % (len(n_dual_filings), n_dual, out_path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
