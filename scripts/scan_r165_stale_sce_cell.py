#!/usr/bin/env python
"""R165 scan - an SCE cell left at a PRE-AMENDMENT value (campaign issue #31).

Found by camp_run on Hanwha Ocean 2015FY amendments r20170511004419 and
r20171019000325: in the separate SCE closing-balance row the 이익잉여금 cell
still holds the value from before the restatement (-1,563,903,332,495) while
every other cell in that row, including the total (415,242,474,443), is the
restated one. Both sibling amendments are wrong in the DB, identically.

Unlike R162/R163 (a missing negative paren) the MAGNITUDE itself is wrong, so
no sign rule can find it.

## Detection - dual evidence, no guessing

For the current-period closing-balance row of an SCE:

  1. ROW IDENTITY   sum(component columns) must equal the total column.
  2. BS ANCHOR      each component must equal the same concept's line in the
                    SAME filing's balance sheet - an anchor OUTSIDE the SCE.

A cell is flagged only when all of these hold:
  · the row identity is broken,
  · EXACTLY ONE component disagrees with the balance sheet,
  · substituting the balance-sheet value makes the identity close exactly.

Then the true value is pinned twice over, and the defect is pinned to one cell.
Anything less is reported as a separate bucket and never repaired.

Hanwha Ocean check: 1,372,076,840,000 - 14,677,080,363 + 14,967,109,054
+ 424,385,260,709 = 1,796,752,129,400; 415,242,474,443 - that = -1,381,509,654,957
= the separate BS 이익잉여금. Error 182,393,677,538.

This script only reads. Repair is a separate decision - correcting a single
cell cannot go through `manual_report_lines` (that drops the whole scope), so
it needs an R159-style exception list.

Usage:
    python scripts/scan_r165_stale_sce_cell.py
    python scripts/scan_r165_stale_sce_cell.py --detail 30 --out <path>
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

# SCE cells. SCE keeps every col_index (it is not in _PERIOD_AXIS_STATEMENTS),
# so no col_index filter here.
_SCE_SQL = """
SELECT rcept_no, basis, row_order, label_raw, col_index, col_label, value_won
FROM report_lines
WHERE statement = 'SCE' AND report_fiscal_year >= 2015
  AND col_label IS NOT NULL AND value_won IS NOT NULL
"""

# BS anchor. BS stores only the current period (col_index = 0).
_BS_SQL = """
SELECT rcept_no, basis, label_raw, value_won
FROM report_lines
WHERE statement = 'BS' AND report_fiscal_year >= 2015
  AND coalesce(col_index, 0) = 0 AND value_won IS NOT NULL
"""

_CLOSING_RE = re.compile(r"기\s*말\s*자\s*본|기\s*말")
_TOTAL_RE = re.compile(r"^(자\s*본)?\s*(합\s*계|총\s*계)$")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def concept(col_label: str) -> str:
    return norm((col_label or "").split(">")[-1])


def _family(loaded: int, true: int) -> str:
    """Which defect family is this? ★Do not lump them together.

    The BS-anchored test finds any disagreement, and three different causes
    land in it. Reporting one number for all three would inflate R165 and hide
    the other two (the "같은 증상 != 같은 원인" lesson, memory note
    `feedback-do-not-attribute-backfill-recoveries-to-one-rule`).

      sign   same magnitude, opposite sign      -> R162/R163 family
      scale  an exact power-of-ten multiple     -> R157-R159 family
      trunc  truncated before scaling           -> R157 family
      other  none of the above                  -> CANDIDATES for R165, but
             this bucket is NOT all issue #31. Digit-level corruption lands
             here too (e.g. 174,044,351,834 loaded as 1,744,044,351,834 - a
             duplicated digit, not a pre-amendment value). Subdividing it
             needs the source, so this scan reports it as unclassified rather
             than claiming an R165 count.
    """
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
        # Truncated before scaling: 336,920,482,688 -> 336,920,482 (R157).
        # An exact power-of-ten ratio is already caught above, so this only
        # picks up the cases that LOSE the remainder.
        for k in range(1, 7):
            if lo == hi // (10 ** k):
                return "trunc"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", type=int, default=15)
    ap.add_argument("--out", help="write flagged rcept_no list here")
    args = ap.parse_args()

    with get_session() as s:
        sce = s.execute(text(_SCE_SQL)).mappings().all()
        bs_rows = s.execute(text(_BS_SQL)).mappings().all()
    print("SCE cells: %d   BS cells: %d" % (len(sce), len(bs_rows)))

    bs: dict = defaultdict(dict)
    for r in bs_rows:
        bs[(r["rcept_no"], r["basis"])].setdefault(norm(r["label_raw"]),
                                                   r["value_won"])

    rows: dict = defaultdict(dict)
    for r in sce:
        rows[(r["rcept_no"], r["basis"], r["row_order"], r["label_raw"])][
            concept(r["col_label"])] = r["value_won"]

    # Current-period closing row = the LAST closing row of each (filing, basis).
    closing: dict = {}
    for key in rows:
        rcept, basis, ro, label = key
        if not _CLOSING_RE.search(label or ""):
            continue
        cur = closing.get((rcept, basis))
        if cur is None or ro > cur[0]:
            closing[(rcept, basis)] = (ro, key)

    n_checked = 0
    n_ok = 0
    flagged: list = []
    no_bs = 0
    multi = 0
    unexplained = 0

    for (rcept, basis), (_ro, key) in closing.items():
        cols = rows[key]
        totals = [c for c in cols if _TOTAL_RE.match(c) or c.endswith("합계")]
        comps = [c for c in cols if c not in totals]
        if len(totals) != 1 or len(comps) < 2:
            continue
        total = cols[totals[0]]
        n_checked += 1
        if sum(cols[c] for c in comps) == total:
            n_ok += 1
            continue

        anchors = bs.get((rcept, basis), {})
        if not anchors:
            no_bs += 1
            continue

        mismatched = []
        for c in comps:
            a = anchors.get(c)
            if a is not None and a != cols[c]:
                mismatched.append((c, cols[c], a))
        if len(mismatched) != 1:
            (multi if mismatched else unexplained)
            if mismatched:
                multi += 1
            else:
                unexplained += 1
            continue

        c, loaded, anchor = mismatched[0]
        implied = total - sum(cols[x] for x in comps if x != c)
        if implied != anchor:
            unexplained += 1
            continue
        flagged.append({"rcept_no": rcept, "basis": basis, "label": key[3],
                        "concept": c, "loaded": loaded, "true": anchor,
                        "total": total, "error": abs(loaded - anchor),
                        "family": _family(loaded, anchor)})

    print("\nclosing rows with a single total and >=2 components : %d" % n_checked)
    print("  row identity holds                                : %d" % n_ok)
    print("  ★broken + exactly one BS mismatch that closes it  : %d" % len(flagged))
    print("  broken, several cells disagree with the BS        : %d" % multi)
    print("  broken, BS does not explain it                    : %d" % unexplained)
    print("  broken, no BS loaded for that basis               : %d" % no_bs)

    if flagged:
        fam: dict = {}
        for f in flagged:
            fam[f["family"]] = fam.get(f["family"], 0) + 1
        print("\n★family split (three different causes land in this test):")
        for k in ("sign", "scale", "trunc", "other"):
            n = fam.get(k, 0)
            filings = len({f["rcept_no"] for f in flagged if f["family"] == k})
            note = {"sign": "R162/R163 - missing negative paren",
                    "scale": "R157-R159 - exact unit/scale multiple",
                    "trunc": "R157 - truncated before scaling",
                    "other": "★unclassified - R165 candidates, NOT all #31"}[k]
            print("  %-6s %5d cell(s)  %5d filing(s)   %s" % (k, n, filings, note))
        flagged = [f for f in flagged if f["family"] == "other"]
        flagged.sort(key=lambda f: -f["error"])
        print("\nunclassified cells only, largest error first:")
        for f in flagged[:args.detail]:
            print("  %s %-13s %-22s %s" % (
                f["rcept_no"], f["basis"], f["label"][:22], f["concept"][:24]))
            print("      loaded=%22s  true(BS)=%22s  err=%s" % (
                "{:,}".format(f["loaded"]), "{:,}".format(f["true"]),
                "{:,}".format(f["error"])))
        corps = len({f["rcept_no"] for f in flagged})
        print("\n  %d cell(s) across %d filing(s)" % (len(flagged), corps))

    if args.out and flagged:
        Path(args.out).write_text(
            "\n".join(sorted({f["rcept_no"] for f in flagged})) + "\n")
        print("  filing list -> %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
