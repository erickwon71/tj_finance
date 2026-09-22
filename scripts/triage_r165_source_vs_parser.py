#!/usr/bin/env python
"""R165 triage - is the wrong SCE cell the SOURCE's fault or OURS?

`scan_r165_stale_sce_cell.py` flags SCE closing-row cells that disagree with
the same filing's balance sheet, where substituting the BS value closes the row
identity exactly. It classifies the obvious families (sign, scale, truncation)
and leaves the rest unclassified. That leftover bucket is where issue #31
lives - but it cannot all be issue #31, and the distinction that matters most
is not which family it is:

    SOURCE  the SCE cell in the XML literally holds the wrong number
            -> a filer defect (issue #31 / R165). We transcribed faithfully.

    PARSER  the XML holds the right number and we loaded something else
            -> OUR bug, and a far more serious one, because every other cell we
               read from that table is suspect too.

Reporting a "source defect" count without separating these would be exactly the
mistake the memory note `feedback-do-not-attribute-backfill-recoveries-to-one-rule`
warns about. So this script goes to the XML and looks.

Read-only. Nothing is repaired.

Usage:
    python scripts/triage_r165_source_vs_parser.py --limit 120
    python scripts/triage_r165_source_vs_parser.py --rcept 20170511004419
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"

_CLOSING_RE = re.compile(r"기\s*말")
_TOTAL_RE = re.compile(r"^(자\s*본)?\s*(합\s*계|총\s*계)$")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def concept(col_label: str) -> str:
    return norm((col_label or "").split(">")[-1])


def _family(loaded: int, true: int) -> str:
    if loaded == -true:
        return "sign"
    if loaded and true:
        hi, lo = abs(loaded), abs(true)
        if hi < lo:
            hi, lo = lo, hi
        if lo and hi % lo == 0:
            q = hi // lo
            while q % 10 == 0:
                q //= 10
            if q == 1:
                return "scale"
        for k in range(1, 7):
            if lo == hi // (10 ** k):
                return "trunc"
    return "other"


def _forms(v: int) -> list:
    """How the magnitude could be printed, across plausible unit scalings."""
    out = []
    for div in (1, 1000, 1000000):
        if v % div == 0:
            out.append("{:,}".format(abs(v) // div))
    return out


def _find_candidates(session, rcepts=None):
    where = "AND rcept_no = ANY(:r)" if rcepts else ""
    sce = session.execute(text("""
        SELECT rcept_no, basis, row_order, label_raw, col_label, value_won
        FROM report_lines
        WHERE statement='SCE' AND report_fiscal_year >= 2015
          AND col_label IS NOT NULL AND value_won IS NOT NULL %s""" % where),
        ({"r": rcepts} if rcepts else {})).mappings().all()
    bs_rows = session.execute(text("""
        SELECT rcept_no, basis, label_raw, value_won
        FROM report_lines
        WHERE statement='BS' AND report_fiscal_year >= 2015
          AND coalesce(col_index,0)=0 AND value_won IS NOT NULL %s""" % where),
        ({"r": rcepts} if rcepts else {})).mappings().all()

    bs: dict = {}
    for r in bs_rows:
        bs.setdefault((r["rcept_no"], r["basis"]), {}).setdefault(
            norm(r["label_raw"]), r["value_won"])

    rows: dict = {}
    for r in sce:
        rows.setdefault(
            (r["rcept_no"], r["basis"], r["row_order"], r["label_raw"]), {})[
            concept(r["col_label"])] = r["value_won"]

    closing: dict = {}
    for key in rows:
        rcept, basis, ro, label = key
        if not _CLOSING_RE.search(label or ""):
            continue
        cur = closing.get((rcept, basis))
        if cur is None or ro > cur[0]:
            closing[(rcept, basis)] = (ro, key)

    out = []
    for (rcept, basis), (_ro, key) in closing.items():
        cols = rows[key]
        totals = [c for c in cols if _TOTAL_RE.match(c) or c.endswith("합계")]
        comps = [c for c in cols if c not in totals]
        if len(totals) != 1 or len(comps) < 2:
            continue
        total = cols[totals[0]]
        if sum(cols[c] for c in comps) == total:
            continue
        anchors = bs.get((rcept, basis), {})
        mism = [(c, cols[c], anchors[c]) for c in comps
                if anchors.get(c) is not None and anchors[c] != cols[c]]
        if len(mism) != 1:
            continue
        c, loaded, anchor = mism[0]
        if total - sum(cols[x] for x in comps if x != c) != anchor:
            continue
        if _family(loaded, anchor) != "other":
            continue
        out.append({"rcept_no": rcept, "basis": basis, "label": key[3],
                    "concept": c, "loaded": loaded, "true": anchor})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--rcept", action="append")
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    with get_session() as s:
        cands = _find_candidates(s, args.rcept)
        print("unclassified candidates: %d" % len(cands))
        if args.limit and len(cands) > args.limit:
            random.Random(args.seed).shuffle(cands)
            cands = cands[:args.limit]
            print("sampling: %d" % len(cands))
        paths = {r["rcept_no"]: r["file_path"] for r in s.execute(text("""
            SELECT rcept_no, file_path FROM download_tasks
            WHERE rcept_no = ANY(:r) AND file_type='xml'"""),
            {"r": [c["rcept_no"] for c in cands]}).mappings()}

    tally = Counter()
    shown = 0
    for c in cands:
        p = paths.get(c["rcept_no"])
        if not p:
            tally["no file"] += 1
            continue
        path = Path(_SD + p[len(_LINK):]) if p.startswith(_LINK) else Path(p)
        if not path.exists():
            tally["no file"] += 1
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            tally["unreadable"] += 1
            continue

        has_loaded = any(f in raw for f in _forms(c["loaded"]))
        has_true = any(f in raw for f in _forms(c["true"]))
        if has_loaded and not has_true:
            verdict = "SOURCE (only the wrong number is in the file)"
        elif has_loaded and has_true:
            verdict = "SOURCE? both numbers present"
        elif has_true and not has_loaded:
            verdict = "★PARSER (the right number is in the file, we loaded another)"
        else:
            verdict = "neither magnitude found (unit/format differs)"
        tally[verdict] += 1
        if shown < args.show:
            shown += 1
            print("\n  %s %-13s %-20s %s" % (
                c["rcept_no"], c["basis"], c["label"][:20], c["concept"][:20]))
            print("     loaded=%22s  BS=%22s" % (
                "{:,}".format(c["loaded"]), "{:,}".format(c["true"])))
            print("     -> %s" % verdict)

    print("\n=== verdicts ===")
    for k, v in tally.most_common():
        print("  %-58s %d" % (k, v))
    print("\n★'SOURCE' means the filer wrote the wrong number and we copied it "
          "faithfully (R165 / issue #31).\n★'PARSER' would mean our bug - those "
          "must be investigated before any repair list is drawn up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
