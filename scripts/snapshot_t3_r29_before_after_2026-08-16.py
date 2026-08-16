"""
T3 (R29) backfill snapshot — before/after/diff for the T3-5 `build_std_v3.py` rebuild.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §8-1, §6 T3-5/T3-6.)

T3 only touches layer 3 (`_map_rows()` in combine.py) -- no re-extraction, report_lines
is never rewritten. This snapshot is scoped to exactly that claim:
  (c) report_lines whole-corp row count + value_won checksum for the 286 target corps
      -- MUST be bit-identical before/after (proves layer 2 truly untouched).
  (d) std_financials_v3 rows for the 286 target corps (all fields) -- diff shows
      exactly which fields changed (should be net_income only, ~1,142 rows recovered).

Reuses the R28 target-corp list (scripts/eps_r28_target_corps_2026-08-15.txt) --
verified identical to T3's own 286-corp population (all corp_codes in the T3-2
recovery key file are a subset of, and here exactly equal to, that list).

Usage:
  .venv/bin/python scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode before
  .venv/bin/python scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode after
  .venv/bin/python scripts/snapshot_t3_r29_before_after_2026-08-16.py --mode diff
"""
import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import psycopg2                                     # noqa: E402
import psycopg2.extras                               # noqa: E402

CORPS_PATH = os.path.join(_REPO_ROOT, "scripts", "eps_r28_target_corps_2026-08-15.txt")
SNAPSHOT_DIR = os.path.join(_REPO_ROOT, "scripts")

_STD_V3_FIELDS = [
    "corp_code", "fiscal_year", "fiscal_period", "statement_type",
    "total_assets", "total_liabilities", "total_equity",
    "revenue", "cogs", "gross_profit", "sga", "operating_income",
    "net_income", "controlling_ni", "ebitda", "shares_out", "data_quality",
]


def load_target_corps():
    with open(CORPS_PATH, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def snapshot(mode: str):
    corps = load_target_corps()
    print(f"target corps: {len(corps)}")

    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT count(*) AS n, sum(value_won)::text AS checksum
        FROM report_lines WHERE corp_code = ANY(%s)
    """, (corps,))
    wide = cur.fetchone()
    print(f"(c) report_lines whole-corp: rows={wide['n']} checksum={wide['checksum']}")

    cols = ", ".join(_STD_V3_FIELDS)
    cur.execute(f"""
        SELECT {cols} FROM std_financials_v3 WHERE corp_code = ANY(%s)
    """, (corps,))
    std_rows = cur.fetchall()
    print(f"(d) std_financials_v3 rows: {len(std_rows)}")

    out = {"mode": mode, "n_corps": len(corps),
           "whole_corp": dict(wide), "std_v3_rows": std_rows}
    path = os.path.join(SNAPSHOT_DIR, f"t3_r29_snapshot_{mode}_2026-08-16.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved -> {path}")
    conn.close()


def diff():
    before_path = os.path.join(SNAPSHOT_DIR, "t3_r29_snapshot_before_2026-08-16.json")
    after_path = os.path.join(SNAPSHOT_DIR, "t3_r29_snapshot_after_2026-08-16.json")
    with open(before_path, encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, encoding="utf-8") as f:
        after = json.load(f)

    print("=== layer 2 untouched check (report_lines whole-corp) ===")
    b, a = before["whole_corp"], after["whole_corp"]
    print(f"  before: rows={b['n']} checksum={b['checksum']}")
    print(f"  after:  rows={a['n']} checksum={a['checksum']}")
    ok = (b["n"] == a["n"] and b["checksum"] == a["checksum"])
    print("  MATCH (layer 2 untouched, as expected)" if ok
          else "  ** MISMATCH ** -- report_lines changed, investigate before trusting T3")

    def std_key(r):
        return (r["corp_code"], r["fiscal_year"], r["fiscal_period"], r["statement_type"])
    before_std = {std_key(r): r for r in before["std_v3_rows"]}
    after_std = {std_key(r): r for r in after["std_v3_rows"]}
    new_std = set(after_std) - set(before_std)
    gone_std = set(before_std) - set(after_std)
    print(f"\n=== std_financials_v3 row set ===")
    print(f"  before: {len(before_std)}  after: {len(after_std)}  "
          f"new: {len(new_std)}  disappeared: {len(gone_std)}")

    print("\n=== field-by-field diff (only net_income should change) ===")
    changed_fields = {}
    for k in set(before_std) & set(after_std):
        bv, av = before_std[k], after_std[k]
        for field in _STD_V3_FIELDS:
            if field in ("corp_code", "fiscal_year", "fiscal_period", "statement_type"):
                continue
            if bv.get(field) != av.get(field):
                changed_fields.setdefault(field, []).append((k, bv.get(field), av.get(field)))
    for field, changes in sorted(changed_fields.items()):
        print(f"  {field}: {len(changes)} rows changed")
        for k, bval, aval in changes[:5]:
            print(f"    {k}: {bval} -> {aval}")
    if not changed_fields:
        print("  no field changes")

    ni_before_null = sum(1 for r in before_std.values() if r.get("net_income") is None)
    ni_after_null = sum(1 for r in after_std.values() if r.get("net_income") is None)
    print(f"\n=== net_income NULL count (target: 1,187 -> <=45 per §6 T3-6) ===")
    print(f"  before: {ni_before_null}  after: {ni_after_null}")

    other_changed = {f: c for f, c in changed_fields.items() if f != "net_income"}
    print(f"\n=== non-net_income fields changed (want 0) ===")
    print("  none" if not other_changed else f"  ** {list(other_changed)} changed -- investigate **")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["before", "after", "diff"])
    args = ap.parse_args()
    if args.mode == "diff":
        diff()
    else:
        snapshot(args.mode)
