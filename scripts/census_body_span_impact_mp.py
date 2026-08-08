"""
Multiprocess, full-population driver for census_body_span_impact.py — see that file's docstring
for what is measured. Sample runs (2026-08-08) found a small nonzero rate (45/773,416 rows,
0.006%, mostly legacy-FS-classified SCE rows the R11 fix doesn't cover) where the earlier
investigation had reported exactly 0 on a smaller sample — this driver measures the true
population-wide count instead of extrapolating from a sample.

Read-only. Does not touch the DB pipeline. See docs/plans/note_span_fix_plan_2026-08-07.md §3
(T3.4).
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for census_body_span_impact
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for collector.db (project root)

from collector.db import engine
from sqlalchemy import text
from concurrent.futures import ProcessPoolExecutor


def work(fp):
    """Returns (status, tables, rows, values, rows_differ, values_differ, examples)."""
    from pathlib import Path as _P
    from census_body_span_impact import (
        _parse_xml_file, assign_tables_to_dart_sections, DART_BODY_SECTIONS, SEC_LEGACY_FS,
        _table_has_data_rows, expanded_rows, _amounts_from_cells,
    )
    try:
        root = _parse_xml_file(_P(fp))
    except Exception:
        return ("parse_err", 0, 0, 0, 0, 0, [])
    if root is None:
        return ("parse_err", 0, 0, 0, 0, 0, [])

    cnt = Counter()
    examples = []
    secs = assign_tables_to_dart_sections(root)
    body_codes = set(DART_BODY_SECTIONS) | {SEC_LEGACY_FS}
    for sec_code, tables in secs.items():
        if sec_code not in body_codes:
            continue
        for table in tables:
            if not _table_has_data_rows(table, minimum=1):
                continue
            cnt["tables"] += 1
            for phys, full in expanded_rows(table):
                if not phys:
                    continue
                a = _amounts_from_cells(phys)
                b = _amounts_from_cells(full)
                if a is None and b is None:
                    continue
                cnt["rows"] += 1
                n_vals = sum(1 for v in (a or []) if v is not None)
                cnt["values"] += n_vals
                if a != b and (any(v is not None for v in (a or []))
                               or any(v is not None for v in (b or []))):
                    cnt["rows_differ"] += 1
                    diff_vals = sum(1 for i in range(3)
                                    if (a or [None] * 3)[i] != (b or [None] * 3)[i])
                    cnt["values_differ"] += diff_vals
                    if len(examples) < 3:
                        examples.append((sec_code, phys[:8], full[:8], a, b))

    return ("ok", cnt["tables"], cnt["rows"], cnt["values"], cnt["rows_differ"],
            cnt["values_differ"], examples)


if __name__ == "__main__":
    t0 = time.time()
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM report_lines WHERE statement <> 'note'")).fetchall()]
        rows = conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall()
        paths = dict(rows)
    print(f"filings to scan: {len(rcepts)} (path lookup {time.time()-t0:.0f}s)", flush=True)

    items = []
    missing = 0
    for r in rcepts:
        fp = paths.get(r)
        if fp:
            items.append((r, fp))
        else:
            missing += 1
    print(f"missing file_path for {missing} rcept_no (skipped)", flush=True)

    n_ok = n_err = 0
    grand = Counter()  # tables, rows, values, rows_differ, values_differ
    all_examples = []
    t1 = time.time()
    fps = [fp for _, fp in items]
    rcept_by_fp = {fp: r for r, fp in items}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(work, fps, chunksize=8)):
            status, tables, rows_, values, rows_differ, values_differ, examples = res
            if status == "ok":
                n_ok += 1
                grand["tables"] += tables
                grand["rows"] += rows_
                grand["values"] += values
                grand["rows_differ"] += rows_differ
                grand["values_differ"] += values_differ
                if examples and len(all_examples) < 40:
                    fp = fps[i]
                    for sec_code, phys, full, a, b in examples:
                        all_examples.append((rcept_by_fp.get(fp, "?"), sec_code, phys, full, a, b))
            else:
                n_err += 1
            if (i + 1) % 5000 == 0:
                el = time.time() - t1
                rate = (i + 1) / el
                eta = (len(fps) - (i + 1)) / rate if rate > 0 else 0
                print(f"...{i+1}/{len(fps)} ({el:.0f}s, {rate:.1f}/s, eta {eta/60:.1f}min) "
                      f"ok={n_ok} err={n_err} rows_differ={grand['rows_differ']} "
                      f"rows={grand['rows']}", flush=True)

    print("=" * 70)
    print(f"total filings   : {len(fps)}")
    print(f"parsed ok       : {n_ok}")
    print(f"parse errors    : {n_err}")
    print(f"body tables     : {grand['tables']:,}")
    print(f"body rows       : {grand['rows']:,}")
    print(f"body values     : {grand['values']:,}")
    print(f"rows where span expansion CHANGES the emitted amounts : "
          f"{grand['rows_differ']:,} ({grand['rows_differ']/max(1,grand['rows'])*100:.4f}%)")
    print(f"value slots changed : {grand['values_differ']:,} "
          f"({grand['values_differ']/max(1,grand['values'])*100:.4f}% of body values)")
    print(f"elapsed total   : {time.time()-t0:.0f}s")
    print("=" * 70)
    for rcept, sec, phys, full, a, b in all_examples[:30]:
        print(f"\n{rcept} [{sec}]")
        print(f"  physical cells : {phys}")
        print(f"  expanded cells : {full}")
        print(f"  pipeline emits : {a}")
        print(f"  expanded emits : {b}")
