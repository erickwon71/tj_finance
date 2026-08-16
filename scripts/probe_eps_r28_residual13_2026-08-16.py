"""
R28 follow-up track T1-0
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §2-1).

Recover the curated keys that still violate the R28 lossless invariant, i.e. keys
whose EPS-path row was suppressed by the skip-gate but that never reappeared as a
main-pass row.

The original invariant checker lived in a scratchpad and was lost. It does not need
rebuilding from scratch: the `after` snapshot produced by
`scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode after` already carries
`main_matched_rows`, which *is* the invariant's right-hand side. So:

    residual = curated_keys - {key(r) for r in after.main_matched_rows}

Measured 2026-08-16: 13 residual keys, all statement=IS / table_seq=0, 13 distinct
rcept_no across 9 corps -- every one of those corps IS in the 286-corp R28 target
list, so re-extraction coverage is not the cause (see design doc §2-2 for the three
real causes).

Note the snapshot JSON is ~42MB and git-untracked. If it is gone, re-create it with
  .venv/bin/python scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode after

Usage:
  .venv/bin/python scripts/probe_eps_r28_residual13_2026-08-16.py
  .venv/bin/python scripts/probe_eps_r28_residual13_2026-08-16.py --out <path.json>
"""
import argparse
import json
import os
import sys
from collections import Counter

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

SNAPSHOT_AFTER = os.path.join(
    _REPO_ROOT, "scripts", "eps_r28_snapshot_after_2026-08-15.json")
CURATED_KEYS = os.path.join(
    _REPO_ROOT, "fin2", "extract", "data",
    "eps_kgaap_headline_not_eps_keys_2026-08-15.json")
DEFAULT_OUT = os.path.join(
    _REPO_ROOT, "scripts", "eps_r28_residual13_2026-08-16.json")


def load_curated_keys(path: str) -> list[tuple]:
    """The data file is a plain list of 5-element lists; tolerate a dict wrapper too."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("keys", raw.get("rows", []))
    out = []
    for k in raw:
        if isinstance(k, dict):
            k = (k["rcept_no"], k["statement"], k["basis"],
                 k["table_seq"], k["label_raw"])
        out.append((k[0], k[1], k[2], int(k[3]), k[4]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=SNAPSHOT_AFTER)
    ap.add_argument("--keys", default=CURATED_KEYS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    if not os.path.exists(args.snapshot):
        sys.exit(f"snapshot not found: {args.snapshot}\n"
                 "  re-create it with: .venv/bin/python "
                 "scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode after")

    keys = load_curated_keys(args.keys)
    print(f"curated keys: {len(keys)}")

    with open(args.snapshot, encoding="utf-8") as f:
        snap = json.load(f)
    matched = {(r["rcept_no"], r["statement"], r["basis"],
                int(r["table_seq"]), r["label_raw"])
               for r in snap["main_matched_rows"]}
    print(f"main-pass rows matching a curated key (distinct keys): {len(matched)}")

    missing = [k for k in keys if k not in matched]
    print(f"\n=== residual keys (no main-pass row): {len(missing)} ===")
    for k in missing:
        print(f"  rcept={k[0]}  stmt={k[1]}  basis={k[2]}  table_seq={k[3]}")
        print(f"    label={' '.join(k[4].split())[:110]}")

    print("\n--- shape of the residual set ---")
    for field, idx in (("statement", 1), ("basis", 2), ("table_seq", 3)):
        print(f"  by {field}: {dict(Counter(k[idx] for k in missing))}")
    print(f"  distinct rcept_no: {len({k[0] for k in missing})}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump([list(k) for k in missing], f, ensure_ascii=False, indent=1)
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
