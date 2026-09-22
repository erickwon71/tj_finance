#!/usr/bin/env python
"""R162-d proof step - how many candidates carry a SECOND, independent anchor?

`scripts/scan_r162d_row_identity.py` finds cells whose sign the SCE's own
within-row identity determines. That identity alone is one anchor. R162's
established standard is DUAL evidence: direction from a cross-reference,
eligibility from an identity (docs/PARSING_RULES.md R162).

The second anchor here is the source itself: if the same magnitude appears
somewhere in the same document INSIDE PARENTHESES while the SCE cell prints it
bare, then the filer wrote the negative elsewhere and dropped it in the SCE -
the exact R162 signature, confirmed without leaving the document.

This script reads only; it repairs nothing.

Usage:
    python scripts/prove_r162d_dual_evidence.py --limit 200
    python scripts/prove_r162d_dual_evidence.py            # all candidates
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.scan_r162d_row_identity import _roles, concept  # noqa: E402

_NAS = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"

_CELLS_SQL = """
SELECT rcept_no, basis, row_order, label_raw, col_index, col_label, value_won
FROM report_lines
WHERE statement = 'SCE' AND report_fiscal_year >= 2015
  AND col_label IS NOT NULL AND value_won IS NOT NULL
  AND rcept_no = ANY(:r)
"""


def _candidates(session, rcepts):
    rows = session.execute(text(_CELLS_SQL), {"r": rcepts}).mappings().all()
    by_row = defaultdict(dict)
    for r in rows:
        by_row[(r["rcept_no"], r["basis"], r["row_order"], r["label_raw"])][
            (concept(r["col_label"]), r["col_index"])] = r["value_won"]
    out = defaultdict(list)
    for key, cols in by_row.items():
        owners, nci, total, _amb = _roles(cols)
        if owners is None or nci is None or total is None:
            continue
        o, n, t = owners[2], nci[2], total[2]
        if o + n == t:
            continue
        closers = []
        if o - n == t and n > 0:
            closers.append(("nci", nci))
        if n - o == t and o > 0:
            closers.append(("owners", owners))
        if o + n == -t and t > 0:
            closers.append(("total", total))
        if len(closers) == 1:
            role, cell = closers[0]
            out[key[0]].append((key, role, cell[2]))
    return out


def _forms(v: int) -> list[str]:
    out = []
    for div in (1, 1000, 1000000):
        if v % div == 0:
            out.append("{:,}".format(v // div))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20260922)
    args = ap.parse_args()

    with get_session() as s:
        rcepts = list(s.execute(text("""
            SELECT DISTINCT rcept_no FROM report_lines
            WHERE statement='SCE' AND report_fiscal_year >= 2015
        """)).scalars().all())
        cands = _candidates(s, rcepts)
        print("candidate filings: %d" % len(cands))
        keys = sorted(cands)
        if args.limit and len(keys) > args.limit:
            import random
            random.Random(args.seed).shuffle(keys)
            keys = keys[:args.limit]
            print("sampling: %d" % len(keys))

        paths = {r["rcept_no"]: r["file_path"] for r in s.execute(text("""
            SELECT rcept_no, file_path FROM download_tasks
            WHERE rcept_no = ANY(:r) AND file_type='xml'"""),
            {"r": keys}).mappings()}

    dual = 0
    single = 0
    unreadable = 0
    by_role_dual: dict = {}
    by_role_single: dict = {}
    for i, rcept in enumerate(keys, 1):
        p = paths.get(rcept)
        if not p:
            unreadable += 1
            continue
        path = Path(_SD + p[len(_NAS):]) if p.startswith(_NAS) else Path(p)
        if not path.exists():
            unreadable += 1
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            unreadable += 1
            continue
        for _key, role, val in cands[rcept]:
            has_paren = any(("(%s)" % f) in raw for f in _forms(abs(val)))
            if has_paren:
                dual += 1
                by_role_dual[role] = by_role_dual.get(role, 0) + 1
            else:
                single += 1
                by_role_single[role] = by_role_single.get(role, 0) + 1
        if i % 100 == 0:
            print("  ... %d/%d" % (i, len(keys)), flush=True)

    tot = dual + single
    print("\ncells examined: %d   (filings unreadable: %d)" % (tot, unreadable))
    if tot:
        print("  ★dual evidence (identity + same magnitude in parens elsewhere): "
              "%d (%.1f%%)" % (dual, 100.0 * dual / tot))
        print("   identity only                                              : "
              "%d (%.1f%%)" % (single, 100.0 * single / tot))
    print("\n  by role - dual:")
    for k in sorted(by_role_dual):
        print("    %-7s %d" % (k, by_role_dual[k]))
    print("  by role - identity only:")
    for k in sorted(by_role_single):
        print("    %-7s %d" % (k, by_role_single[k]))
    print("\n★The paren test is a WITHIN-DOCUMENT coincidence check, not a cell "
          "match - the same magnitude could belong to an unrelated concept. It "
          "raises confidence; it does not replace per-cell proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
