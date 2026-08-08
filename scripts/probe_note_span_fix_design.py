"""
Design probe for the ROWSPAN/COLSPAN fix — turns two guesses into measurements.

Q1. If body rows are span-expanded, every row spans the full grid width, so the current
    `n_amounts = max(len(physical cells) - 1)` collapses to `width - 1` and `offset`
    becomes 1 for every table. What should replace it?
    Candidate L = number of LEADING grid columns that never hold a parseable amount in
    any body row. Does L reproduce today's `offset` on tables that are NOT span-affected
    (i.e. is the new scheme backward-compatible where today's output is already right)?

Q2. How much of the damage is "value in wrong column" vs "row label itself inherited"?
    A row whose grid column 0 is occupied by an inherited ROWSPAN has no label cell of
    its own -- the pipeline stores its 2nd logical cell as label_raw. Count those rows.

Raw XML only. Read-only.
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
from fin2.extract.report_lines import _cell_span, _get_cells, _NUMBER_PATTERN
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
    n_amounts = 0
    for tr in trs[n_header:]:
        n_amounts = max(n_amounts, max(0, len(_get_cells(tr)) - 1))
    if n_amounts == 0:
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
    offset = width - n_amounts
    if offset < 0:
        return
    cnt["tables"] += 1

    # walk body rows on the continuing grid; record where amounts truly land
    amount_cols = set()
    table_defect = False
    inherited_label_rows = 0
    body_rows = 0
    for i, tr in enumerate(trs[n_header:]):
        r = n_header + i
        cells_text = _get_cells(tr)
        if not cells_text:
            continue
        body_rows += 1
        if (r, 0) in occupied:          # grid col 0 carried over by an inherited ROWSPAN
            inherited_label_rows += 1
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
        for k in range(len(true_cols)):
            raw = cells_text[k] if k < len(cells_text) else ""
            if parse_amount(raw, 1) is not None:
                amount_cols.add(true_cols[k])
                if k >= 1 and true_cols[k] != offset + (k - 1):
                    table_defect = True

    if not amount_cols:
        return
    # L = leading grid columns that never hold an amount anywhere in the body
    L = 0
    while L < width and L not in amount_cols:
        L += 1

    cnt["tables_with_amounts"] += 1
    cnt["inherited_label_rows"] += inherited_label_rows
    cnt["body_rows"] += body_rows
    bucket = "defect" if table_defect else "clean"
    cnt[f"{bucket}_tables"] += 1
    if L == offset:
        cnt[f"{bucket}_L_eq_offset"] += 1
    else:
        cnt[f"{bucket}_L_ne_offset"] += 1
        cnt[f"{bucket}_delta{L - offset:+d}"] += 1


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
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

    print(f"filings {len(sample)} (err {cnt['err']}) tables_with_amounts "
          f"{cnt['tables_with_amounts']:,}")
    print()
    print("Q1. proposed L (leading non-amount grid cols) vs today's offset")
    for b in ("clean", "defect"):
        tot = cnt[f"{b}_tables"] or 1
        print(f"  {b:6s} tables {cnt[f'{b}_tables']:>7,} | "
              f"L == offset {cnt[f'{b}_L_eq_offset']:>7,} "
              f"({cnt[f'{b}_L_eq_offset']/tot*100:5.1f}%) | "
              f"L != offset {cnt[f'{b}_L_ne_offset']:>7,}")
        deltas = sorted((k, v) for k, v in cnt.items() if k.startswith(f"{b}_delta"))
        if deltas:
            print("           deltas: " + "  ".join(
                f"{k.split('delta')[1]}:{v:,}" for k, v in deltas))
    print()
    print("Q2. rows whose own label cell is missing (grid col 0 inherited via ROWSPAN)")
    br = cnt["body_rows"] or 1
    print(f"  {cnt['inherited_label_rows']:,} / {cnt['body_rows']:,} body rows "
          f"({cnt['inherited_label_rows']/br*100:.2f}%)")


if __name__ == "__main__":
    main()
