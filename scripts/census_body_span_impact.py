"""
Does the same ROWSPAN/COLSPAN body-row defect affect report_lines (BS/IS/CF face tables)?

The body path is NOT the note path: it calls extract_rows(keep_all_amount_cells=False),
which routes cells through _split_label_amounts() -- that drops non-numeric cells and
pulls amounts left, and then drops leading None amounts (6-column IS realignment).
That behaviour may absorb a missing leading cell on its own.

Equivalence test: for every body statement table, compute the emitted amount sequence
(a) exactly as the pipeline does, from the physical cells, and
(b) from a ROWSPAN/COLSPAN-EXPANDED row (inherited cells materialised with their text).
If (a) == (b) for every row, span expansion changes nothing for the body and the defect
is confined to the note path.

Read-only. Raw XML only -- no DB values are used as truth.
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
    assign_tables_to_dart_sections, table_direct_rows,
    DART_BODY_SECTIONS, SEC_LEGACY_FS,
)
from fin2.extract.report_lines import _cell_span, _get_cells, _split_label_amounts
from fin2.extract.text import _table_has_data_rows
from parser.common.amount_normalizer import parse_amount

BODY_SECTIONS = None  # filled from the section keys we see; BS/IS/CF only


def _amounts_from_cells(cells, num_cols=3):
    """Replicates extract_rows()'s amount handling for the body path."""
    label, amount_cells = _split_label_amounts(cells)
    if not label:
        return None
    parsed = [parse_amount(ac, 1) for ac in amount_cells]
    if len(parsed) >= 4:
        while parsed and parsed[0] is None:
            parsed.pop(0)
    return [parsed[i] if i < len(parsed) else None for i in range(num_cols)]


def expanded_rows(table):
    """Yield (physical_cells, span_expanded_cells) per body row of the table."""
    trs = table_direct_rows(table)
    if not trs:
        return
    # occupied grid carrying inherited ROWSPAN text, built over ALL rows in order
    occ: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(trs):
        phys = _get_cells(tr)
        c = 0
        placed: dict[int, str] = {}
        for td in tr:
            tag = td.tag.upper() if isinstance(td.tag, str) else ""
            if tag not in ("TD", "TH", "TE", "TU"):
                continue
            while (r, c) in occ:
                c += 1
            txt = "".join(td.itertext()).strip()
            cs, rs = _cell_span(td, "COLSPAN"), _cell_span(td, "ROWSPAN")
            for dr in range(rs):
                for dc in range(cs):
                    if dr > 0:            # only future rows inherit
                        occ[(r + dr, c + dc)] = txt
            # a COLSPAN'd cell contributes its text once, then blanks for the rest
            for dc in range(cs):
                placed[c + dc] = txt if dc == 0 else ""
            c += cs
        width = max(placed) + 1 if placed else 0
        inherited_here = {col: t for (rr, col), t in occ.items() if rr == r}
        width = max([width] + [k + 1 for k in inherited_here]) if inherited_here else width
        full = []
        for col in range(width):
            if col in placed:
                full.append(placed[col])
            else:
                full.append(inherited_here.get(col, ""))
        yield phys, full


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    random.seed(20260807)
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM report_lines WHERE statement <> 'note'"
        )).fetchall()]
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
    pool = [(r, paths[r]) for r in rcepts if paths.get(r)]
    sample = random.sample(pool, min(n, len(pool)))

    cnt = Counter()
    examples = []
    for rcept, fp in sample:
        try:
            root = _parse_xml_file(Path(fp))
        except Exception:
            cnt["parse_err"] += 1
            continue
        if root is None:
            cnt["parse_err"] += 1
            continue
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
                                        if (a or [None]*3)[i] != (b or [None]*3)[i])
                        cnt["values_differ"] += diff_vals
                        if len(examples) < 25 and random.random() < 0.3:
                            examples.append((rcept, sec_code, phys[:8], full[:8], a, b))

    print(f"filings sampled : {len(sample)}  (parse errors {cnt['parse_err']})")
    print(f"body tables     : {cnt['tables']:,}")
    print(f"body rows       : {cnt['rows']:,}")
    print(f"body values     : {cnt['values']:,}")
    print(f"rows where span expansion CHANGES the emitted amounts : "
          f"{cnt['rows_differ']:,} ({cnt['rows_differ']/max(1,cnt['rows'])*100:.3f}%)")
    print(f"value slots changed : {cnt['values_differ']:,} "
          f"({cnt['values_differ']/max(1,cnt['values'])*100:.3f}% of body values)")
    print("=" * 70)
    for rcept, sec, phys, full, a, b in examples[:15]:
        print(f"\n{rcept} [{sec}]")
        print(f"  physical cells : {phys}")
        print(f"  expanded cells : {full}")
        print(f"  pipeline emits : {a}")
        print(f"  expanded emits : {b}")


if __name__ == "__main__":
    main()
