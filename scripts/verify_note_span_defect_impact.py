"""
Independent re-verification of the ROWSPAN/COLSPAN census (2026-08-07 handoff).

Goal: the raw census counts a "defect" whenever true grid column != assumed column.
That says nothing about whether the stored data is actually WRONG. Here we classify
each defect instance by its real impact and cross-check against what the DB holds.

Classifications per defect value:
  - label_none_both : neither assumed nor true column has a header label (col_label NULL
                      either way) -> stored row is identical, defect is cosmetic only
  - label_same      : assumed and true column carry the SAME label text -> harmless
  - label_diff      : stored col_label is genuinely the wrong column's label
  - mult_diff       : on top of label_diff, the unit multiplier differs -> value_won wrong

Also flags a possible census artifact: rows where the number of TR child elements
differs from the number of cells _get_cells() returns (index misalignment).
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
from fin2.extract.units import ColumnUnits
from fin2.extract.text import declaration_text, inherited_declaration_text
from parser.common.amount_normalizer import parse_amount

CELL_TAGS = ("TD", "TH", "TE", "TU")


def _cell_text(td) -> str:
    return " ".join("".join(td.itertext()).split())


def analyze_table(table, samples, counter):
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

    grid: dict[tuple[int, int], str] = {}
    occupied: set[tuple[int, int]] = set()
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

    # exact same label dict the pipeline builds
    col_labels: dict[int, str] = {}
    for col in range(offset, width):
        parts = []
        for r in range(n_header):
            t = grid.get((r, col))
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        if parts:
            col_labels[col - offset] = ">".join(parts)

    own_decl = declaration_text(table)
    inherited = None if own_decl else inherited_declaration_text(table)
    cu = ColumnUnits.from_declaration(own_decl or inherited, col_labels,
                                      inherited=bool(inherited))

    for i, tr in enumerate(trs[n_header:]):
        r = n_header + i
        cells_text = _get_cells(tr)
        if not cells_text:
            continue

        # census artifact check: does `for td in tr` align with _get_cells indices?
        n_children = len(list(tr))
        aligned = (n_children == len(cells_text))

        true_cols = []
        c = 0
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
            counter["amount_values"] += 1
            assumed = offset + (k - 1)
            true_c = true_cols[k]
            if true_c == assumed:
                continue
            counter["defect_values"] += 1
            if not aligned:
                counter["misaligned_tr"] += 1

            a_idx, t_idx = assumed - offset, true_c - offset
            a_lab, t_lab = col_labels.get(a_idx), col_labels.get(t_idx)
            a_mult = cu.multiplier(a_idx)
            t_mult = cu.multiplier(t_idx)

            if a_lab is None and t_lab is None:
                kind = "label_none_both"
            elif a_lab == t_lab:
                kind = "label_same"
            elif a_mult == t_mult:
                kind = "label_diff"
            elif a_mult is None:
                # pipeline left value_won NULL (value_raw kept) but the true column IS a
                # money column -> value missing, not corrupted. Recoverable from raw.
                kind = "mult_dropped"
            elif t_mult is None:
                # pipeline multiplied a value that truly sits in a NON-money column
                # (rate/ratio/count) -> bogus magnitude stored. The POSCO 7.35e15 pattern.
                kind = "mult_bogus"
            else:
                kind = "mult_scale"     # both money, different scale -> wrong magnitude
            counter[kind] += 1
            counter[f"shift{true_c - assumed:+d}"] += 1

            if len(samples) < 400 and random.random() < 0.02:
                samples.append({
                    "kind": kind, "raw": raw, "row_label": cells_text[0][:40],
                    "k": k, "assumed_idx": a_idx, "true_idx": t_idx,
                    "assumed_label": a_lab, "true_label": t_lab,
                    "assumed_mult": a_mult, "true_mult": t_mult,
                    "aligned": aligned, "n_cells": len(cells_text),
                    "decl": (own_decl or inherited or "")[:40],
                    "cells": cells_text[:10],
                })


def analyze_filing(fp, samples, counter):
    root = _parse_xml_file(Path(fp))
    if root is None:
        return
    sec_tables = assign_note_tables_with_titles(root)
    for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for table, _title in sec_tables.get(sec_kind, []):
            if _table_has_data_rows(table, minimum=1):
                analyze_table(table, samples, counter)


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
    sample_filings = random.sample(pool, min(n, len(pool)))

    counter = Counter()
    samples = []
    for rcept, fp in sample_filings:
        try:
            analyze_filing(fp, samples, counter)
        except Exception as e:
            counter["errors"] += 1

    av = counter["amount_values"] or 1
    dv = counter["defect_values"] or 1
    print(f"filings sampled     : {len(sample_filings)}  (errors {counter['errors']})")
    print(f"amount values       : {counter['amount_values']}")
    print(f"defect values (raw) : {counter['defect_values']}  "
          f"({counter['defect_values']/av*100:.2f}%)")
    print("-" * 66)
    print("impact breakdown of the raw defect count:")
    for kind in ("label_none_both", "label_same", "label_diff",
                 "mult_dropped", "mult_bogus", "mult_scale"):
        print(f"  {kind:16s}: {counter[kind]:>9,}  ({counter[kind]/dv*100:5.1f}% of defects,"
              f" {counter[kind]/av*100:5.2f}% of all values)")
    print(f"  TR/_get_cells index misalignment in defect rows: {counter['misaligned_tr']:,}")
    print("-" * 66)
    print("shift distribution (true_col - assumed_col):")
    for key, cnt in sorted((k, v) for k, v in counter.items() if k.startswith("shift")):
        print(f"  {key}: {cnt:,}")

    print("=" * 66)
    print("SAMPLE CASES (for raw-XML cross-check)")
    random.shuffle(samples)
    by_kind = {}
    for s in samples:
        by_kind.setdefault(s["kind"], []).append(s)
    for kind, items in by_kind.items():
        print(f"\n### {kind}  ({len(items)} sampled)")
        for s in items[:6]:
            print(f"  row={s['row_label']!r} cells={s['cells']}")
            print(f"    value={s['raw']!r} physical_k={s['k']} decl={s['decl']!r}")
            print(f"    stored: col_index={s['assumed_idx']} label={s['assumed_label']!r} "
                  f"mult={s['assumed_mult']}")
            print(f"    true  : col_index={s['true_idx']} label={s['true_label']!r} "
                  f"mult={s['true_mult']}")


if __name__ == "__main__":
    main()
