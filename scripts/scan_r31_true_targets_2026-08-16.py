"""
R31(T22) precise target-filing scan (Phase 5 prep, refines the grep prefilter).

The grep prefilter (`>-[0-9][0-9,]*(\\.[0-9]+)?</T[DE]>` over pre-2010 raw XML) is a
cheap but very loose proxy -- it matches ANY bare hyphen-negative cell ANYWHERE in the
document (notes, XBRL fact cells, ratios...), not just the specific body-table gate
defect T22 fixes. It flagged 1,352/2,538 corps (53%) -- far more than the ~7% impact
rate the Phase 1 census measured, and reloading that many corps' entire report_lines
history would not be a "targeted" backfill.

This does the PRECISE check instead: run the real `extract_report_lines()` before
(R31-pre-fix pattern, monkeypatched) / after (current, fixed) on every grep-flagged
filing, restricted to BS/IS/CF, and keep only filings where at least one row is
classified "corrected" or "new_value" (same logic as
`census_t22_hyphen_negative_2026-08-16.py`). That is the TRUE target-corp list for
`reload_report_lines_corp.py`.

Multiprocessing (CPU-bound XML parse + extraction) -- 10 cores available.

Usage:
  .venv/bin/python scripts/scan_r31_true_targets_2026-08-16.py
"""
from __future__ import annotations

import multiprocessing as mp
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402

CANDIDATES = Path("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                   "c71ac0f4-a792-4dcc-ab3d-2157691d3661/scratchpad/t22_matched_files_v3.txt")
OUT = Path("/Users/taejin/Project/tj_finance/scripts/"
           "r31_true_target_filings_2026-08-16.tsv")

_INSERT_AFTER = r'^\(-\)[\d,]+\.?\d*$|'
_NEW_ALT = r'^-[\d,]+\.?\d*$|'


def _worker_init():
    global te, rl, ORIG_PATTERN, EXT_UNUSED
    import parser.xml.table_extractor as te_mod
    import fin2.extract.report_lines as rl_mod
    te = te_mod
    rl = rl_mod
    ORIG_PATTERN = te.__dict__["_NUMBER_PATTERN"]  # current = fixed (R31) pattern


def _pre_r31_pattern():
    base = te._NUMBER_PATTERN.pattern
    assert _NEW_ALT.rstrip('|') in base, "R31 alt not found in current pattern (unexpected)"
    return re.compile(base.replace(_NEW_ALT, "", 1))


def row_identity(line):
    if line.row_order is not None:
        return (line.statement, line.basis, line.table_seq, "R", line.row_order)
    return (line.statement, line.basis, line.table_seq, "L", (line.label_raw or "")[:40])


def check_one(args):
    rcept, corp, fy, period, path = args
    if not Path(path).exists():
        return None
    try:
        pre = _pre_r31_pattern()
        te._NUMBER_PATTERN = pre
        rl._NUMBER_PATTERN = pre
        before = rl.extract_report_lines(
            path, rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period, include_notes=False)
        te._NUMBER_PATTERN = ORIG_PATTERN
        rl._NUMBER_PATTERN = ORIG_PATTERN
        after = rl.extract_report_lines(
            path, rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period, include_notes=False)
    except Exception as e:  # noqa: BLE001
        return ("ERROR", rcept, corp, f"{type(e).__name__}: {e}")
    finally:
        te._NUMBER_PATTERN = ORIG_PATTERN
        rl._NUMBER_PATTERN = ORIG_PATTERN

    def bmap(lines):
        out = {}
        for ln in lines:
            if ln.statement not in ("BS", "IS", "CF"):
                continue
            out.setdefault(row_identity(ln), {})[ln.col_index] = ln.value_won
        return out

    b, a = bmap(before), bmap(after)
    hit = False
    for ident in set(b) | set(a):
        bb, aa = b.get(ident, {}), a.get(ident, {})
        if bb != aa:
            hit = True
            break
    return ("HIT" if hit else "NOHIT", rcept, corp, "")


def main():
    matched_paths = set(CANDIDATES.read_text().splitlines())
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT dt.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, dt.file_path
            FROM filings f JOIN download_tasks dt USING (rcept_no)
            WHERE dt.file_type='xml' AND dt.status='completed' AND dt.file_path IS NOT NULL
              AND f.fiscal_year <= 2010
        """)).fetchall()
    RAW_NAS = "/Users/taejin/Project/tj_finance/raw_report/"
    RAW_SD = "/Volumes/dart_data/raw_report/"
    jobs = []
    for r in rows:
        p = r.file_path
        sd = RAW_SD + p[len(RAW_NAS):] if p.startswith(RAW_NAS) else p
        resolved = sd if Path(sd).exists() else p
        if resolved in matched_paths:
            jobs.append((r.rcept_no, r.corp_code, r.fiscal_year, r.fiscal_period, resolved))
    print(f"candidate filings to precisely check: {len(jobs)}")

    n_hit = n_nohit = n_err = n_missing = 0
    hits = []
    with mp.Pool(10, initializer=_worker_init) as pool:
        for i, res in enumerate(pool.imap_unordered(check_one, jobs, chunksize=20), 1):
            if res is None:
                n_missing += 1
            elif res[0] == "HIT":
                n_hit += 1
                hits.append(res)
            elif res[0] == "NOHIT":
                n_nohit += 1
            else:
                n_err += 1
                print(f"  !! {res[1]} {res[2]}: {res[3]}")
            if i % 1000 == 0:
                print(f"  ... {i}/{len(jobs)}  hit={n_hit} nohit={n_nohit} "
                      f"err={n_err} missing={n_missing}")

    print(f"\nDONE. candidates={len(jobs)} HIT={n_hit} NOHIT={n_nohit} "
          f"ERROR={n_err} MISSING={n_missing}")
    corps = sorted({h[2] for h in hits})
    print(f"true target corps: {len(corps)}")
    with open(OUT, "w", encoding="utf-8") as f:
        for _, rcept, corp, _ in hits:
            f.write(f"{rcept}\t{corp}\n")
    print(f"Saved -> {OUT}")
    corps_path = Path("/Users/taejin/Project/tj_finance/scripts/t22_target_corps_2026-08-16.txt")
    with open(corps_path, "w", encoding="utf-8") as f:
        for c in corps:
            f.write(c + "\n")
    print(f"Overwrote -> {corps_path} (precise target list, {len(corps)} corps)")


if __name__ == "__main__":
    main()
