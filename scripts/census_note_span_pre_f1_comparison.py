"""
Was the note-path column misattribution introduced by F1 (2026-07-31)?

F1 switched the note path to extract_rows(keep_all_amount_cells=True) +
_build_col_labels(all_cells=True), i.e. PHYSICAL cell positions are preserved so that
non-numeric cells keep their slot. Before F1 the note path used the same
_split_label_amounts() filtering the body path still uses, which pulls amounts left.

This measures, on the SAME tables, the column misattribution rate under both regimes:
  - post-F1 (current): amount at physical cell k -> grid col offset_all + (k-1)
  - pre-F1  (former) : i-th SURVIVING amount cell -> grid col offset_split + i
against the ROWSPAN/COLSPAN-expanded grid as ground truth in both cases.

Raw XML only; no DB values used as truth.
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_note_tables_with_titles, SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from fin2.extract.text import _table_has_data_rows
from fin2.extract.report_lines import (
    _cell_span, _get_cells, _split_label_amounts, _NUMBER_PATTERN,
)
from parser.common.amount_normalizer import parse_amount


def _cell_text(td):
    return " ".join("".join(td.itertext()).split())


def analyze(table, cnt):
    trs = table_direct_rows(table)
    if not trs:
        return
    n_header = 0
    for tr in trs:
        cells = [_cell_text(td) for td in tr]
        if len(cells) > 1 and any(_NUMBER_PATTERN.search(c) for c in cells[1:]):
            break
        n_header += 1
    if n_header == 0 or n_header >= len(trs):
        return

    # two different n_amounts, exactly as _build_col_labels computes them
    n_all = n_split = 0
    for tr in trs[n_header:]:
        cells = _get_cells(tr)
        n_all = max(n_all, max(0, len(cells) - 1))
        _, amt = _split_label_amounts(cells)
        n_split = max(n_split, len(amt))
    if n_all == 0 or n_split == 0:
        return

    occupied = set()
    for r, tr in enumerate(trs[:n_header]):
        c = 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
            c += cs
    width = max((col for _, col in occupied), default=0) + 1
    off_all, off_split = width - n_all, width - n_split
    if off_all < 0 or off_split < 0:
        return

    for i, tr in enumerate(trs[n_header:]):
        r = n_header + i
        cells_text = _get_cells(tr)
        if not cells_text:
            continue
        true_cols, c = [], 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            true_cols.append(c)
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
            c += cs

        # ---- post-F1 (current pipeline) ----
        for k in range(1, len(true_cols)):
            raw = cells_text[k] if k < len(cells_text) else ""
            if parse_amount(raw, 1) is None:
                continue
            cnt["postF1_values"] += 1
            if true_cols[k] != off_all + (k - 1):
                cnt["postF1_defects"] += 1

        # ---- pre-F1 (_split_label_amounts, amounts pulled left) ----
        label, amt_cells = _split_label_amounts(cells_text)
        if not label:
            continue
        # map each surviving amount cell back to its physical index
        phys_idx, used = [], 0
        for k in range(1, len(cells_text)):
            if used < len(amt_cells) and cells_text[k] == amt_cells[used]:
                phys_idx.append(k)
                used += 1
        if used != len(amt_cells):
            cnt["pre_unmappable_rows"] += 1
            continue
        parsed = [parse_amount(a, 1) for a in amt_cells]
        drop = 0
        if len(parsed) >= 4:
            while drop < len(parsed) and parsed[drop] is None:
                drop += 1
        for j in range(drop, len(parsed)):
            if parsed[j] is None:
                continue
            cnt["preF1_values"] += 1
            k = phys_idx[j]
            if k < len(true_cols) and true_cols[k] != off_split + (j - drop):
                cnt["preF1_defects"] += 1


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    random.seed(20260807)
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
    pool = [(r, paths[r]) for r in rcepts if paths.get(r)]
    sample = random.sample(pool, min(n, len(pool)))

    cnt = Counter()
    for rcept, fp in sample:
        try:
            root = _parse_xml_file(Path(fp))
        except Exception:
            cnt["err"] += 1
            continue
        if root is None:
            cnt["err"] += 1
            continue
        secs = assign_note_tables_with_titles(root)
        for sk in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for table, _t in secs.get(sk, []):
                if _table_has_data_rows(table, minimum=1):
                    analyze(table, cnt)

    print(f"filings sampled : {len(sample)} (errors {cnt['err']})")
    print(f"post-F1 (current) : {cnt['postF1_defects']:,} / {cnt['postF1_values']:,} "
          f"= {cnt['postF1_defects']/max(1,cnt['postF1_values'])*100:.2f}%")
    print(f"pre-F1  (former)  : {cnt['preF1_defects']:,} / {cnt['preF1_values']:,} "
          f"= {cnt['preF1_defects']/max(1,cnt['preF1_values'])*100:.2f}%")
    print(f"rows the pre-F1 back-mapping could not resolve (excluded): "
          f"{cnt['pre_unmappable_rows']:,}")


if __name__ == "__main__":
    main()
