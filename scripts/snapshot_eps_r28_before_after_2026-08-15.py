"""
Phase 3/5 of the R28 rollout
(docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md
§8 Phase 3-1/5-4).

Snapshot the state relevant to the R28 fix for the 286 target corps
(scripts/eps_r28_target_corps_2026-08-15.txt), before and after re-extraction,
so Phase 5 can diff them instead of assuming "no side effects".

Captures per §8 Phase 3-1:
  (a) report_lines EPS-path rows (section_path='주당손익') for the 286 corps,
  (b) report_lines main-pass rows (row_order IS NOT NULL) matching the same
      (rcept_no, statement, basis, table_seq, label_raw) as the curated keys,
  (c) whole-corp report_lines row count + value_won checksum (catches
      unintended broad-scope changes),
  (d) std_financials_v3 rows for the 286 corps (all fields, keyed).

Usage:
  .venv/bin/python scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode before
  .venv/bin/python scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode after
  .venv/bin/python scripts/snapshot_eps_r28_before_after_2026-08-15.py --mode diff
"""
import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import psycopg2
import psycopg2.extras

CORPS_PATH = os.path.join(_REPO_ROOT, "scripts", "eps_r28_target_corps_2026-08-15.txt")
KEYS_PATH = os.path.join(_REPO_ROOT, "fin2", "extract", "data",
                          "eps_kgaap_headline_not_eps_keys_2026-08-15.json")
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


def load_keys():
    with open(KEYS_PATH, encoding="utf-8") as f:
        return [tuple(k) for k in json.load(f)]


def snapshot(mode: str):
    corps = load_target_corps()
    keys = load_keys()
    key_set = set(keys)
    print(f"target corps: {len(corps)}, curated keys: {len(keys)}")

    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # (a) EPS-path rows for the target corps.
    cur.execute("""
        SELECT rcept_no, statement, basis, table_seq, label_raw, col_index, corp_code, value_won
        FROM report_lines
        WHERE corp_code = ANY(%s) AND section_path = '주당손익'
    """, (corps,))
    eps_rows = cur.fetchall()
    print(f"(a) EPS-path rows: {len(eps_rows)}")

    # (b) main-pass rows matching curated keys exactly -- filter in SQL via a temp
    # table JOIN, not by pulling every main-pass row for 286 corps into Python
    # (that's every BS/IS/CF/SCE row across decades -- too slow, see design §8 Phase 3
    # implementation note).
    cur.execute("""
        CREATE TEMP TABLE _eps_r28_keys (
            rcept_no text, statement text, basis text, table_seq int, label_raw text
        ) ON COMMIT DROP
    """)
    psycopg2.extras.execute_values(
        cur,
        "INSERT INTO _eps_r28_keys (rcept_no, statement, basis, table_seq, label_raw) VALUES %s",
        keys,
    )
    cur.execute("""
        SELECT rl.rcept_no, rl.statement, rl.basis, rl.table_seq, rl.label_raw,
               rl.col_index, rl.corp_code, rl.value_won
        FROM report_lines rl
        JOIN _eps_r28_keys k
          ON rl.rcept_no = k.rcept_no AND rl.statement = k.statement AND rl.basis = k.basis
         AND rl.table_seq = k.table_seq AND rl.label_raw = k.label_raw
        WHERE rl.row_order IS NOT NULL
    """)
    main_matched = cur.fetchall()
    print(f"(b) main-pass rows matching curated keys: {len(main_matched)}")

    # (c) whole-corp report_lines row count + value_won checksum.
    cur.execute("""
        SELECT count(*) AS n, sum(value_won)::text AS checksum
        FROM report_lines WHERE corp_code = ANY(%s)
    """, (corps,))
    wide = cur.fetchone()
    print(f"(c) report_lines whole-corp: rows={wide['n']} checksum={wide['checksum']}")

    # (d) std_financials_v3 rows for target corps.
    cols = ", ".join(_STD_V3_FIELDS)
    cur.execute(f"""
        SELECT {cols} FROM std_financials_v3 WHERE corp_code = ANY(%s)
    """, (corps,))
    std_rows = cur.fetchall()
    print(f"(d) std_financials_v3 rows: {len(std_rows)}")

    out = {
        "mode": mode,
        "n_corps": len(corps),
        "n_keys": len(keys),
        "eps_rows": eps_rows,
        "main_matched_rows": main_matched,
        "whole_corp": dict(wide),
        "std_v3_rows": std_rows,
    }
    path = os.path.join(SNAPSHOT_DIR, f"eps_r28_snapshot_{mode}_2026-08-15.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved -> {path}")
    conn.close()


def diff():
    before_path = os.path.join(SNAPSHOT_DIR, "eps_r28_snapshot_before_2026-08-15.json")
    after_path = os.path.join(SNAPSHOT_DIR, "eps_r28_snapshot_after_2026-08-15.json")
    with open(before_path, encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, encoding="utf-8") as f:
        after = json.load(f)

    def row_key(r):
        return (r["rcept_no"], r["statement"], r["basis"], r["table_seq"], r["label_raw"], r["col_index"])

    print("=== 5-1. EPS-path rows for curated keys: expect gone after ===")
    keys = set(tuple(k) for k in json.load(open(KEYS_PATH, encoding="utf-8")))
    def is_curated(r):
        return (r["rcept_no"], r["statement"], r["basis"], r["table_seq"], r["label_raw"]) in keys
    before_eps_curated = {row_key(r) for r in before["eps_rows"] if is_curated(r)}
    after_eps_curated = {row_key(r) for r in after["eps_rows"] if is_curated(r)}
    print(f"  before: {len(before_eps_curated)}  after: {len(after_eps_curated)} (want 0)")

    print("\n=== 5-2. Main-pass rows generated for curated keys: expect 100% coverage ===")
    after_main = {row_key(r): r["value_won"] for r in after["main_matched_rows"]}
    before_main = {row_key(r): r["value_won"] for r in before["main_matched_rows"]}
    new_main = set(after_main) - set(before_main)
    print(f"  before main-matched: {len(before_main)}  after: {len(after_main)}  new: {len(new_main)}")

    print("\n=== 5-3. Non-curated EPS rows: expect completely unchanged ===")
    before_eps_noncurated = {row_key(r): r["value_won"] for r in before["eps_rows"] if not is_curated(r)}
    after_eps_noncurated = {row_key(r): r["value_won"] for r in after["eps_rows"] if not is_curated(r)}
    only_before = set(before_eps_noncurated) - set(after_eps_noncurated)
    only_after = set(after_eps_noncurated) - set(before_eps_noncurated)
    changed_value = {k for k in set(before_eps_noncurated) & set(after_eps_noncurated)
                      if before_eps_noncurated[k] != after_eps_noncurated[k]}
    print(f"  only_before(missing after)={len(only_before)} only_after(new)={len(only_after)} "
          f"value_changed={len(changed_value)}  (want all 0)")

    print("\n=== 5-4. std_financials_v3 diff (record, don't assume 'no change') ===")
    def std_key(r):
        return (r["corp_code"], r["fiscal_year"], r["fiscal_period"], r["statement_type"])
    before_std = {std_key(r): r for r in before["std_v3_rows"]}
    after_std = {std_key(r): r for r in after["std_v3_rows"]}
    changed_fields = {}
    for k in set(before_std) & set(after_std):
        b, a = before_std[k], after_std[k]
        for field in _STD_V3_FIELDS:
            if field in ("corp_code", "fiscal_year", "fiscal_period", "statement_type"):
                continue
            if b.get(field) != a.get(field):
                changed_fields.setdefault(field, []).append((k, b.get(field), a.get(field)))
    for field, changes in changed_fields.items():
        print(f"  {field}: {len(changes)} rows changed")
        for k, bv, av in changes[:5]:
            print(f"    {k}: {bv} -> {av}")
    if not changed_fields:
        print("  no field changes")
    new_std = set(after_std) - set(before_std)
    gone_std = set(before_std) - set(after_std)
    print(f"  new std_v3 rows: {len(new_std)}  disappeared: {len(gone_std)}")

    print("\n=== whole-corp checksum (unintended broad-scope changes) ===")
    print(f"  before: rows={before['whole_corp']['n']} checksum={before['whole_corp']['checksum']}")
    print(f"  after:  rows={after['whole_corp']['n']} checksum={after['whole_corp']['checksum']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["before", "after", "diff"])
    args = ap.parse_args()
    if args.mode == "diff":
        diff()
    else:
        snapshot(args.mode)
