"""
R31(T22) pre-DB-write sanity check — TODO Phase 4.
docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md Phase 4.

4-1: re-run the NOW-FIXED production `extract_report_lines()` (no monkeypatch -- the fix is
     permanent in parser/xml/table_extractor.py) over every rcept_no in the Phase 1 census
     results CSV, and confirm the resulting (col_index -> value_won) map for each flagged row
     matches the "after" column recorded during Phase 1 census exactly.
4-2: confirm the T1 group-A 6 residual keys now emit at col_index=0 (loadable).

Read-only -- no DB writes.
"""
import ast
import csv
import sys
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402
import fin2.extract.report_lines as rl  # noqa: E402

CSV_PATH = Path("/Users/taejin/Project/tj_finance/scripts/"
                 "census_t22_hyphen_negative_2026-08-16_results.csv")
RAW_REPORT_NAS = "/Users/taejin/Project/tj_finance/raw_report/"
RAW_REPORT_SD = "/Volumes/dart_data/raw_report/"


def resolve_path(file_path: str) -> str:
    if file_path.startswith(RAW_REPORT_NAS):
        sd = RAW_REPORT_SD + file_path[len(RAW_REPORT_NAS):]
        if Path(sd).exists():
            return sd
    return file_path


def row_identity(line):
    if line.row_order is not None:
        return (line.statement, line.basis, line.table_seq, "R", line.row_order)
    return (line.statement, line.basis, line.table_seq, "L", (line.label_raw or "")[:40])


def check_4_1():
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rcepts = sorted({r["rcept_no"] for r in rows})
    with engine.connect() as conn:
        meta = {r.rcept_no: r for r in conn.execute(text("""
            SELECT rcept_no, corp_code, fiscal_year, fiscal_period, file_path
            FROM filings f JOIN download_tasks dt USING (rcept_no)
            WHERE rcept_no = ANY(:r) AND dt.file_type='xml'
        """), {"r": rcepts}).fetchall()}

    n_ok, n_bad = 0, 0
    for rcept in rcepts:
        m = meta.get(rcept)
        if not m:
            print(f"  !! {rcept}: no filing/download_tasks row")
            continue
        path = resolve_path(m.file_path)
        if not Path(path).exists():
            print(f"  !! {rcept}: xml missing at {path}")
            continue
        lines = rl.extract_report_lines(
            path, rcept_no=rcept, corp_code=m.corp_code,
            report_fiscal_year=m.fiscal_year, report_fiscal_period=m.fiscal_period,
            include_notes=False)
        current: dict = {}
        for ln in lines:
            if ln.statement not in ("BS", "IS", "CF"):
                continue
            ident = row_identity(ln)
            current.setdefault(ident, {})[ln.col_index] = ln.value_won

        for r in [r for r in rows if r["rcept_no"] == rcept]:
            row_order = int(r["row_order"]) if r["row_order"] else None
            ident = (r["statement"], r["basis"], int(r["table_seq"]),
                      "R" if row_order is not None else "L",
                      row_order if row_order is not None else r["label_raw"][:40])
            expected = ast.literal_eval(r["after"])
            got = current.get(ident, {})
            if got == expected:
                n_ok += 1
            else:
                n_bad += 1
                print(f"  MISMATCH {rcept} {ident}: expected(census after)={expected} "
                      f"got(current fixed code)={got}")
    print(f"4-1: {n_ok} rows match census 'after' exactly, {n_bad} mismatches "
          f"({len(rcepts)} filings re-extracted with the fixed code)")


def check_4_2():
    import subprocess
    out = subprocess.run(
        [".venv/bin/python", "scripts/probe_eps_r28_residual13_cause_2026-08-16.py",
         "--mode", "run"],
        cwd="/Users/taejin/Project/tj_finance", capture_output=True, text=True)
    print(out.stdout)
    if out.returncode != 0:
        print(out.stderr)
    loaded = out.stdout.count("LOADED")
    dropped = out.stdout.count("<< DROPPED by _is_loadable")
    print(f"4-2: LOADED={loaded} DROPPED={dropped} "
          f"(group A expects the 6 group-A keys now LOADED at col_index=0)")


if __name__ == "__main__":
    print("=" * 70)
    print("Phase 4-1 — re-extract with the fixed code, diff against census 'after'")
    check_4_1()
    print("=" * 70)
    print("Phase 4-2 — T1 group-A residual 13 keys, --mode run")
    check_4_2()
