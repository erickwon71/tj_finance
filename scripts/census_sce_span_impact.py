"""
T1.4 (docs/plans/note_span_fix_plan_2026-08-07.md, Phase 1) — does the ROWSPAN/COLSPAN
body-row defect (handoff §1, confirmed for note_lines) also affect SCE (자본변동표)?

SCE is a THIRD, separate code path from both body (BS/IS/CF) and notes:
  `_emit_sce_lines` -> extract_rows(preserve_col_positions=True, date_labels_ok=True,
                                    keep_all_amount_cells=False (default))
i.e. it still runs cells through `_split_label_amounts()` (which DROPS non-numeric cells
and does NOT reinsert them -- unlike notes' `keep_all_amount_cells=True`), but it does NOT
do the body path's "6-column IS leading-blank trim" (that's what `census_body_span_impact.py`
found absorbs the defect for BS/IS/CF). So SCE's absorption behavior is genuinely unverified
and needs its own measurement -- this script.

Same equivalence-test methodology as `census_body_span_impact.py`: for every SCE table, compare
the amount sequence the pipeline emits from (a) physical cells vs (b) ROWSPAN/COLSPAN-expanded
cells. If they differ, span-unaware extraction is losing/misplacing a value for that row.

Uses the REAL production table-detection path (`_detect_body_statement_tables(..., include_sce=True)`)
so the population matches exactly what `_emit_sce_lines` sees -- not a re-derived approximation.

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
from parser.xml.section_detector import table_direct_rows
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type
from fin2.extract.report_lines import _cell_span, _get_cells, _split_label_amounts
from parser.common.amount_normalizer import parse_amount

_PAD = 20  # generous -- real SCE tables rarely exceed a dozen capital-component columns


def _amounts_from_cells(cells):
    """Replicates extract_rows(preserve_col_positions=True)'s amount handling for SCE:
    _split_label_amounts (drops non-numeric cells, KEEPS '-'/blank) then NO leading-blank
    trim (that trim is explicitly skipped when preserve_col_positions=True)."""
    label, amount_cells = _split_label_amounts(cells)
    if not label:
        return None
    parsed = [parse_amount(ac, 1) for ac in amount_cells]
    return [parsed[i] if i < len(parsed) else None for i in range(_PAD)]


def expanded_rows(table):
    """Yield (physical_cells, span_expanded_cells) per row of the table -- identical
    construction to census_body_span_impact.py's `expanded_rows`."""
    trs = table_direct_rows(table)
    if not trs:
        return
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
                    if dr > 0:
                        occ[(r + dr, c + dc)] = txt
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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    random.seed(20260807)
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM report_lines WHERE statement = 'SCE'"
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
        fin_type = _detect_fin_type(root)
        groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
        for sec_code in ("SCE_C", "SCE_S"):
            for table, _unit, _ in groups.get(sec_code, []):
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
                        diff_vals = sum(1 for i in range(_PAD)
                                        if (a or [None]*_PAD)[i] != (b or [None]*_PAD)[i])
                        cnt["values_differ"] += diff_vals
                        if len(examples) < 25 and random.random() < 0.5:
                            examples.append((rcept, sec_code, phys[:10], full[:10], a[:10], b[:10]))

    print(f"filings sampled : {len(sample)}  (parse errors {cnt['parse_err']})")
    print(f"SCE tables      : {cnt['tables']:,}")
    print(f"SCE rows        : {cnt['rows']:,}")
    print(f"SCE values      : {cnt['values']:,}")
    print(f"rows where span expansion CHANGES the emitted amounts : "
          f"{cnt['rows_differ']:,} ({cnt['rows_differ']/max(1,cnt['rows'])*100:.3f}%)")
    print(f"value slots changed : {cnt['values_differ']:,} "
          f"({cnt['values_differ']/max(1,cnt['values'])*100:.3f}% of SCE values)")
    print("=" * 70)
    for rcept, sec, phys, full, a, b in examples[:15]:
        print(f"\n{rcept} [{sec}]")
        print(f"  physical cells : {phys}")
        print(f"  expanded cells : {full}")
        print(f"  pipeline emits : {a}")
        print(f"  expanded emits : {b}")


if __name__ == "__main__":
    main()
