"""
R28 follow-up track T3-2 -- rekey the R28 curated key set for layer-3 consumption.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §6 T3-2.)

`combine.py::_map_rows()` (the T3 injection site, §4-3) has no `rcept_no` in scope --
its cell-merge key is `(statement, basis, col_index, section_path, label_raw)` --
so the curated 5-tuple key `(rcept_no, statement, basis, table_seq, label_raw)` can't be
used as-is there. This rekeys it to `(corp_code, fiscal_year, fiscal_period, basis) ->
{label_raw}`, which IS in scope (§4-3 confirmed `_map_rows()` gets `corp`/`fy` added as
selected args, and the call sites already have `period`/`basis`).

Feasibility was already measured in the design doc (§4-3, reproduced here as the
completion check): 2,205 curated keys -> 1,840 groups, 0 unmatched rcept_no, max 2
labels/group (median 1).

DB READ-ONLY (joins against `filings` for the rcept_no -> corp/fy/period lookup).
No DB writes, no report_lines/std_v3 changes.

Usage:
  .venv/bin/python scripts/build_ni_recovery_keys_2026-08-16.py
"""
import json
import os
import sys
from collections import defaultdict

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text                        # noqa: E402

from collector.db import get_session                # noqa: E402

CURATED_KEYS = os.path.join(
    _REPO_ROOT, "fin2", "extract", "data",
    "eps_kgaap_headline_not_eps_keys_2026-08-15.json")

# Output location -- fin2/extract/data/ for now (same directory as the curated source
# it's derived from). §6 T3-3 confirms/overrides this before T3-4 wires it in.
OUT_PATH = os.path.join(
    _REPO_ROOT, "fin2", "extract", "data",
    "eps_kgaap_ni_recovery_keys_2026-08-16.json")


def main():
    with open(CURATED_KEYS, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("keys", raw.get("rows", []))
    keys = [tuple(k) for k in raw]
    print(f"curated keys loaded: {len(keys)}")

    rcepts = sorted({k[0] for k in keys})
    with get_session() as s:
        rows = s.execute(text("""
            SELECT rcept_no, corp_code, fiscal_year, fiscal_period
            FROM filings WHERE rcept_no = ANY(:r)
        """), {"r": rcepts}).fetchall()
    rcept_to_filing = {r.rcept_no: (r.corp_code, r.fiscal_year, r.fiscal_period) for r in rows}

    unmatched = [r for r in rcepts if r not in rcept_to_filing]
    print(f"distinct rcept_no in curated keys: {len(rcepts)}")
    print(f"rcept_no NOT found in filings     : {len(unmatched)}"
          f"{'  ' + str(unmatched[:5]) if unmatched else ''}")

    groups: dict[str, set[str]] = defaultdict(set)
    dropped = 0
    for rcept_no, statement, basis, table_seq, label_raw in keys:
        filing = rcept_to_filing.get(rcept_no)
        if filing is None:
            dropped += 1
            continue
        corp_code, fiscal_year, fiscal_period = filing
        gkey = f"{corp_code}|{fiscal_year}|{fiscal_period}|{basis}"
        groups[gkey].add(label_raw)

    label_counts = [len(v) for v in groups.values()]
    print(f"groups (corp,fy,period,basis)     : {len(groups)}")
    print(f"keys dropped (no filing match)    : {dropped}")
    print(f"labels/group  max={max(label_counts)}  "
          f"median={sorted(label_counts)[len(label_counts) // 2]}")
    multi = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    print(f"groups with 2 labels               : {len(multi)}")

    out = {k: sorted(v) for k, v in sorted(groups.items())}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nwrote {OUT_PATH}  ({len(out)} groups)")

    # Reproduce §4-3's exact numbers so a future re-run is a one-line diff check.
    expected = dict(groups=1840, unmatched=0, max_labels=2, multi_label_groups=36)
    actual = dict(groups=len(groups), unmatched=len(unmatched),
                  max_labels=max(label_counts), multi_label_groups=len(multi))
    print(f"\n§4-3 reproduction check:")
    print(f"  expected: {expected}")
    print(f"  actual  : {actual}")
    print("  MATCH" if expected == actual else "  ** MISMATCH -- investigate before T3-3 **")


if __name__ == "__main__":
    main()
