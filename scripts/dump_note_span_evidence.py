"""
Dump the RAW XML markup of tables where the census flags a column misattribution,
so the finding can be confirmed by reading the original document markup directly
(no DB values involved). Prints header TRs and the offending body TR verbatim.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from lxml import etree
from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_note_tables_with_titles, SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from fin2.extract.text import _table_has_data_rows, declaration_text, inherited_declaration_text
from fin2.extract.report_lines import _cell_span, _get_cells, _NUMBER_PATTERN
from parser.common.amount_normalizer import parse_amount


def _cell_text(td):
    return " ".join("".join(td.itertext()).split())


def _raw(el, limit=900):
    s = etree.tostring(el, encoding="unicode")
    s = " ".join(s.split())
    return s[:limit] + ("..." if len(s) > limit else "")


def scan_table(table, out, rcept, tseq):
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

    grid, occupied = {}, set()
    for r, tr in enumerate(trs[:n_header]):
        c = 0
        for td in tr:
            while (r, c) in occupied:
                c += 1
            txt = _cell_text(td)
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
                    if txt:
                        grid[(r + dr, c + dc)] = txt
            c += cs
    width = max((col for _, col in occupied), default=0) + 1
    offset = width - n_amounts
    if offset < 0:
        return
    col_labels = {}
    for col in range(offset, width):
        parts = []
        for r in range(n_header):
            t = grid.get((r, col))
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        if parts:
            col_labels[col - offset] = ">".join(parts)

    decl = declaration_text(table) or inherited_declaration_text(table)

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
        for k in range(1, len(true_cols)):
            raw = cells_text[k] if k < len(cells_text) else ""
            if parse_amount(raw, 1) is None:
                continue
            assumed, true_c = offset + (k - 1), true_cols[k]
            if true_c == assumed:
                continue
            out.append({
                "rcept": rcept, "tseq": tseq, "row_idx": r,
                "decl": decl, "width": width, "offset": offset, "n_amounts": n_amounts,
                "n_header": n_header,
                "header_raw": [_raw(t, 700) for t in trs[:n_header]],
                "body_raw": _raw(tr, 900),
                "prev_raw": _raw(trs[r - 1], 700) if r > 0 else "",
                "cells": cells_text,
                "value": raw, "k": k,
                "assumed_idx": assumed - offset, "true_idx": true_c - offset,
                "assumed_label": col_labels.get(assumed - offset),
                "true_label": col_labels.get(true_c - offset),
            })
            return  # one example per table is enough


def main():
    targets = sys.argv[1:]
    with engine.connect() as conn:
        if targets:
            rows = conn.execute(text(
                "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
            ), {"r": targets}).fetchall()
            pool = [(r, p) for r, p in rows]
        else:
            rcepts = [r[0] for r in conn.execute(text(
                "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
            paths = dict(conn.execute(text(
                "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
            ), {"r": rcepts}).fetchall())
            random.seed(4242)
            pool = random.sample([(r, paths[r]) for r in rcepts if paths.get(r)], 6)

    for rcept, fp in pool:
        root = _parse_xml_file(Path(fp))
        if root is None:
            print(f"{rcept}: parse failed")
            continue
        sec_tables = assign_note_tables_with_titles(root)
        out, tseq = [], 0
        for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for table, _t in sec_tables.get(sec_kind, []):
                if not _table_has_data_rows(table, minimum=1):
                    continue
                tseq += 1
                scan_table(table, out, rcept, tseq)
                if len(out) >= 2:
                    break
            if len(out) >= 2:
                break
        print("#" * 90)
        print(f"# rcept_no={rcept}  file={fp}")
        for ev in out[:2]:
            print(f"\n--- table_seq={ev['tseq']} n_header={ev['n_header']} "
                  f"grid_width={ev['width']} n_amounts={ev['n_amounts']} offset={ev['offset']}")
            print(f"    unit declaration: {ev['decl']!r}")
            for h in ev["header_raw"]:
                print(f"    HEADER XML : {h}")
            print(f"    PREV ROW XML: {ev['prev_raw']}")
            print(f"    BODY  XML  : {ev['body_raw']}")
            print(f"    parsed cells: {ev['cells']}")
            print(f"    >> value {ev['value']!r} (physical cell #{ev['k']})")
            print(f"       STORED as col_index={ev['assumed_idx']} label={ev['assumed_label']!r}")
            print(f"       TRUE      col_index={ev['true_idx']} label={ev['true_label']!r}")


if __name__ == "__main__":
    main()
