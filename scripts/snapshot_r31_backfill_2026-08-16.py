"""
R31(T22) targeted backfill snapshot — before/after/diff.
docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md Phase 5-1, Phase 6-1/6-2.

Unlike T3(R29) (layer 3 only, report_lines untouched), R31 DOES rewrite report_lines
for the target corps (that is the point -- bare hyphen-negative cells were being
dropped, silently corrupting values). So the invariant here is different:
  - target corps: rows/checksum SHOULD change (that's the fix landing)
  - GLOBAL total - target total = non-target total -- if the global delta equals
    exactly the target delta, non-target rows are proven bit-identical without a
    slow "corp_code NOT IN (1352)" full scan (Phase 6-1).
  - BS identity anomaly count (evidence LIKE 'bs_identity%') for target corps --
    should DECREASE (T21 precedent: this safety net catches the same class of
    silent corruption; a decrease is the expected signature of a real fix, Phase 6-2).
  - std_financials_v3 rows for target corps (delta only, not full diff -- T22 is a
    layer-2 fix, layer-3 numbers move only as a downstream consequence).

Usage:
  .venv/bin/python scripts/snapshot_r31_backfill_2026-08-16.py --mode before
  .venv/bin/python scripts/snapshot_r31_backfill_2026-08-16.py --mode after
  .venv/bin/python scripts/snapshot_r31_backfill_2026-08-16.py --mode diff
"""
import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import psycopg2                                     # noqa: E402
import psycopg2.extras                               # noqa: E402

CORPS_PATH = os.path.join(_REPO_ROOT, "scripts", "t22_target_corps_2026-08-16.txt")
SNAPSHOT_DIR = os.path.join(_REPO_ROOT, "scripts")


def load_target_corps(corps_path):
    with open(corps_path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def snapshot(mode: str, corps_path: str, tag: str):
    corps = load_target_corps(corps_path)
    print(f"target corps: {len(corps)}")
    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT count(*) AS n, sum(value_won)::text AS checksum FROM report_lines")
    global_ = dict(cur.fetchone())
    print(f"global report_lines: rows={global_['n']} checksum={global_['checksum']}")

    cur.execute("""
        SELECT count(*) AS n, sum(value_won)::text AS checksum
        FROM report_lines WHERE corp_code = ANY(%s)
    """, (corps,))
    target = dict(cur.fetchone())
    print(f"target-corp report_lines: rows={target['n']} checksum={target['checksum']}")

    cur.execute("""
        SELECT count(*) AS n
        FROM report_line_anomalies
        WHERE corp_code = ANY(%s) AND evidence LIKE 'bs_identity%%'
    """, (corps,))
    bs_anom = cur.fetchone()["n"]
    print(f"target-corp BS-identity anomalies: {bs_anom}")

    cur.execute("""
        SELECT count(*) AS n, sum(net_income)::text AS ni_sum
        FROM std_financials_v3 WHERE corp_code = ANY(%s)
    """, (corps,))
    std_v3 = dict(cur.fetchone())
    print(f"target-corp std_financials_v3: rows={std_v3['n']} net_income_sum={std_v3['ni_sum']}")

    out = {"mode": mode, "n_corps": len(corps), "global": global_, "target": target,
           "bs_identity_anomalies": bs_anom, "std_v3": std_v3}
    path = os.path.join(SNAPSHOT_DIR, f"r31_backfill_snapshot_{tag}{mode}_2026-08-16.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved -> {path}")
    conn.close()


def diff(tag: str):
    with open(os.path.join(SNAPSHOT_DIR, f"r31_backfill_snapshot_{tag}before_2026-08-16.json"),
              encoding="utf-8") as f:
        before = json.load(f)
    with open(os.path.join(SNAPSHOT_DIR, f"r31_backfill_snapshot_{tag}after_2026-08-16.json"),
              encoding="utf-8") as f:
        after = json.load(f)

    gb, ga = before["global"], after["global"]
    tb, ta = before["target"], after["target"]
    row_delta_global = ga["n"] - gb["n"]
    row_delta_target = ta["n"] - tb["n"]
    chk_delta_global = int(ga["checksum"]) - int(gb["checksum"])
    chk_delta_target = int(ta["checksum"]) - int(tb["checksum"])

    print("=== Phase 6-1: scope-outside invariant (non-target corps untouched) ===")
    print(f"  global row delta  = {row_delta_global:,}   target row delta  = {row_delta_target:,}")
    print(f"  global chk delta  = {chk_delta_global:,}   target chk delta  = {chk_delta_target:,}")
    ok_rows = row_delta_global == row_delta_target
    ok_chk = chk_delta_global == chk_delta_target
    print("  MATCH -- non-target rows bit-identical" if (ok_rows and ok_chk)
          else "  ** MISMATCH ** -- global delta != target delta => something outside "
               "scope changed, investigate before trusting the backfill")

    print("\n=== Phase 6-2: BS identity anomalies (target corps, want DECREASE) ===")
    print(f"  before: {before['bs_identity_anomalies']}  after: {after['bs_identity_anomalies']}")
    delta = after["bs_identity_anomalies"] - before["bs_identity_anomalies"]
    print("  decreased (expected -- T21 precedent)" if delta < 0
          else ("unchanged" if delta == 0 else f"  ** INCREASED by {delta} ** -- investigate"))

    print("\n=== std_financials_v3 (target corps) ===")
    print(f"  rows before={before['std_v3']['n']} after={after['std_v3']['n']}")
    print(f"  net_income sum before={before['std_v3']['ni_sum']} after={after['std_v3']['ni_sum']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["before", "after", "diff"])
    ap.add_argument("--corps-file", default=CORPS_PATH,
                     help="target corp list (default: t22_target_corps_2026-08-16.txt)")
    ap.add_argument("--tag", default="",
                     help="filename prefix to keep separate rounds' snapshots apart "
                          "(e.g. 'delta_' for round 2)")
    args = ap.parse_args()
    if args.mode == "diff":
        diff(args.tag)
    else:
        snapshot(args.mode, args.corps_file, args.tag)
