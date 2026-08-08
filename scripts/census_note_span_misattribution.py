"""
Full precise census — re-parses raw XML for every filing that has note_lines data and
determines, per note table, whether a value cell is mis-assigned to the wrong grid column,
using a from-scratch ROWSPAN/COLSPAN-aware grid reconstruction as ground truth.

Ground truth method: same (row, col) occupied-grid technique `_build_col_labels` already uses
for header rows (fin2/extract/report_lines.py), extended through the body rows. For each row
(header or body) we walk its physical <TD>/<TH> cells left to right, skipping grid columns
still occupied by a ROWSPAN inherited from an earlier row, and reserving COLSPAN x ROWSPAN cells
for each physical cell we place. This gives the TRUE grid column for every physical cell. This
ground-truth walk is written independently in this script — it does NOT call any pipeline code.

Two comparisons are measured per value cell, against the same ground truth:
  - BASELINE: the pre-fix (R11) assumption — physical cell k (k=1,2,... within a row, 0=label)
    sits at grid column `offset + (k-1)`, hardcoded here to reproduce the original bug's size.
    This number is now purely historical reference (2026-08-07 measurement: 28,189,281 defects)
    and does NOT change no matter what the pipeline code does — it never calls pipeline code.
  - POSTFIX: the ACTUAL current pipeline (`parser.xml.table_extractor.expand_table_grid`, the
    R11 fix wired into note/SCE extraction, `fin2/extract/report_lines.py` T2.4/T2.5) — this is
    the real T3.1 check. Calls the production function and compares its per-cell grid_col
    against the same ground truth. Should converge to ~0 if the fix is correct.
  (2026-08-08: added after discovering BASELINE alone can never validate the fix — see
  docs/plans/note_span_fix_plan_2026-08-07.md §3 T3.1.)

Read-only: does not touch the DB pipeline or write anything except this script's own stdout.
Reuses the exact same table-selection functions the real pipeline uses
(`assign_note_tables_with_titles`, `_table_has_data_rows`) so the population matches note_lines.
"""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_note_tables_with_titles, SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from fin2.extract.text import _table_has_data_rows
from fin2.extract.report_lines import _cell_span, _get_cells, _NUMBER_PATTERN
from parser.xml.table_extractor import expand_table_grid
from parser.common.amount_normalizer import parse_amount


def _cell_text(td) -> str:
    return " ".join("".join(td.itertext()).split())


def analyze_table(table):
    """Returns (n_rows_scanned, n_defect_rows_baseline, n_defect_values_baseline,
    n_amount_values_total, n_defect_rows_postfix, n_defect_values_postfix)."""
    trs = table_direct_rows(table)
    if not trs:
        return 0, 0, 0, 0, 0, 0

    # header/body split — same rule _build_col_labels uses.
    n_header = 0
    for tr in trs:
        cells = [_cell_text(td) for td in tr]
        if len(cells) > 1 and any(_NUMBER_PATTERN.search(c) for c in cells[1:]):
            break
        n_header += 1
    if n_header == 0 or n_header >= len(trs):
        return 0, 0, 0, 0, 0, 0

    # n_amounts / width / offset — identical computation to _build_col_labels(all_cells=True)
    n_amounts = 0
    for tr in trs[n_header:]:
        cells = _get_cells(tr)
        n_amounts = max(n_amounts, max(0, len(cells) - 1))
    if n_amounts == 0:
        return 0, 0, 0, 0, 0, 0

    occupied: set[tuple[int, int]] = set()
    origin: dict[tuple[int, int], int] = {}
    for r, tr in enumerate(trs[:n_header]):
        c = 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
                    origin[(r + dr, c + dc)] = r
            c += cs
    width = max((col for _, col in occupied), default=0) + 1
    offset = width - n_amounts
    if offset < 0:
        return 0, 0, 0, 0, 0, 0

    # POSTFIX ground truth source: the actual production grid walk (R11 fix). Called once for
    # the whole table so row indices line up 1:1 with `trs` (same table_direct_rows source).
    grid_rows = expand_table_grid(table)

    n_rows_scanned = 0
    n_defect_rows_baseline = 0
    n_defect_values_baseline = 0
    n_amount_values_total = 0
    n_defect_rows_postfix = 0
    n_defect_values_postfix = 0

    for i, tr in enumerate(trs[n_header:]):
        r = n_header + i
        cells_text = _get_cells(tr)
        if not cells_text:
            continue
        n_rows_scanned += 1

        # true grid walk for THIS row's physical cells (continues the same occupied/origin state)
        true_cols: list[int] = []
        c = 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            true_cols.append(c)
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
                    origin[(r + dr, c + dc)] = r
            c += cs

        # production result for this row: physical (non-inherited) GridCells, left to right —
        # same ordering as `true_cols` (both walk the row's <TD>/<TH> children in DOM order).
        postfix_physical = [gc for gc in grid_rows[r] if not gc.inherited] if r < len(grid_rows) else []

        row_defect_baseline = False
        row_defect_postfix = False
        for k in range(1, len(true_cols)):
            raw = cells_text[k] if k < len(cells_text) else ""
            amount = parse_amount(raw, 1)
            if amount is None:
                continue
            n_amount_values_total += 1
            true_col = true_cols[k]

            # BASELINE: pre-fix assumption — physical cell k -> offset + (k-1). Historical only.
            assumed_col = offset + (k - 1)
            if true_col != assumed_col:
                n_defect_values_baseline += 1
                row_defect_baseline = True

            # POSTFIX: actual current pipeline (expand_table_grid) — the real T3.1 check.
            postfix_col = postfix_physical[k].grid_col if k < len(postfix_physical) else None
            if postfix_col != true_col:
                n_defect_values_postfix += 1
                row_defect_postfix = True

        if row_defect_baseline:
            n_defect_rows_baseline += 1
        if row_defect_postfix:
            n_defect_rows_postfix += 1

    return (n_rows_scanned, n_defect_rows_baseline, n_defect_values_baseline,
            n_amount_values_total, n_defect_rows_postfix, n_defect_values_postfix)


def analyze_filing(file_path: str):
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return None
    sec_tables = assign_note_tables_with_titles(root)
    totals = [0, 0, 0, 0, 0, 0]
    n_tables = 0
    for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for table, _title in sec_tables.get(sec_kind, []):
            if not _table_has_data_rows(table, minimum=1):
                continue
            n_tables += 1
            stats = analyze_table(table)
            for i in range(6):
                totals[i] += stats[i]
    return n_tables, totals


def main():
    t0 = time.time()
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())

    print(f"filings to scan: {len(rcepts)}  (path lookup done, {time.time()-t0:.0f}s)")

    n_filings_ok = 0
    n_filings_err = 0
    n_filings_defect_postfix = 0
    n_tables_total = 0
    # rows_scanned, defect_rows_baseline, defect_values_baseline, amount_values_total,
    # defect_rows_postfix, defect_values_postfix
    grand = [0, 0, 0, 0, 0, 0]
    errors = []

    for i, rcept in enumerate(rcepts):
        fp = paths.get(rcept)
        if not fp:
            n_filings_err += 1
            continue
        try:
            result = analyze_filing(fp)
        except Exception as e:
            n_filings_err += 1
            if len(errors) < 20:
                errors.append((rcept, str(e), traceback.format_exc(limit=3)))
            continue
        if result is None:
            n_filings_err += 1
            continue
        n_tables, stats = result
        n_tables_total += n_tables
        n_filings_ok += 1
        if stats[5] > 0:
            n_filings_defect_postfix += 1
        for k in range(6):
            grand[k] += stats[k]

        if (i + 1) % 2000 == 0:
            el = time.time() - t0
            rate = (i + 1) / el
            eta = (len(rcepts) - (i + 1)) / rate if rate > 0 else 0
            print(f"...{i+1}/{len(rcepts)} ({el:.0f}s elapsed, eta {eta/60:.1f}min) "
                  f"defect_filings_postfix={n_filings_defect_postfix} "
                  f"defect_values_postfix={grand[5]} defect_values_baseline={grand[2]} "
                  f"amount_values_total={grand[3]} errors={n_filings_err}",
                  flush=True)

    print("=" * 70)
    print(f"total filings                       : {len(rcepts)}")
    print(f"parsed ok                           : {n_filings_ok}")
    print(f"parse errors                        : {n_filings_err}")
    print(f"tables scanned                       : {n_tables_total}")
    print(f"rows scanned                         : {grand[0]}")
    print(f"amount values total                  : {grand[3]}")
    print(f"BASELINE defect values (pre-fix, hist): {grand[2]}  ({grand[2]/max(1,grand[3])*100:.2f}%)")
    print(f"BASELINE defect rows                  : {grand[1]}")
    print(f"POSTFIX defect values (actual pipeline): {grand[5]}  ({grand[5]/max(1,grand[3])*100:.2f}%)  <- T3.1 pass/fail")
    print(f"POSTFIX defect rows                    : {grand[4]}")
    print(f"filings with >=1 POSTFIX defect       : {n_filings_defect_postfix} ({n_filings_defect_postfix/max(1,len(rcepts))*100:.1f}%)")
    print(f"elapsed                              : {time.time()-t0:.0f}s")
    if errors:
        print("\nsample errors:")
        for rcept, msg, tb in errors[:10]:
            print(f"  {rcept}: {msg}")


if __name__ == "__main__":
    main()
