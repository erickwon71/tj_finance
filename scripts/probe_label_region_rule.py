"""
T1.1 (docs/plans/note_span_fix_plan_2026-08-07.md, Phase 1) — measure 3 candidate rules for
the label-region width L that will replace `n_amounts = max(physical cell count) - 1` once
body rows are span-expanded (see handoff §11 for why the current formula breaks under
expansion, and §15-1/plan §0-2(B) for why the first candidate tried there was falsified).

All three candidates are derived from the HEADER grid alone (never from body-row physical
cell counts, which is what breaks): they only need the same (row,col) occupied-grid
`_build_col_labels` already builds for header rows.

  Candidate 1: leading grid columns whose text is IDENTICAL across every header row
               (a full-height ROWSPAN'd '구분'-style label column).
  Candidate 2: width - (number of grid columns whose bottom-header-row cell ORIGINATES at
               the bottom row, i.e. is not just an inherited ROWSPAN carry-down). Keeps the
               existing right-alignment formula, but counts amount columns structurally
               instead of by physical body-cell count.
  Candidate 3: candidate1 ∩ candidate2 — agree or abstain (None -> falls back to current
               offset, flagged via unit_source in the real implementation; here just counted
               separately).

Measured result (2026-08-07, 156 filings): all three FAIL badly (11-44% match, far under the
99.9% bar) — see docs/plans/note_span_fix_plan_2026-08-07.md §1 T1.1 for the full table. Root
cause: 41.8% of clean tables have only 1 header row, where NO structural (ROWSPAN/COLSPAN)
signal exists at all to separate the '구분' label column from real amount columns.

  Candidate V:  leading grid columns that never hold a parseable amount ANYWHERE in the body
                (the ORIGINAL candidate from handoff §11 / `probe_note_span_fix_design.py`,
                which was reported falsified — 91.5% match, breaks 8.5% of clean tables when
                a genuine amount column is entirely blank/dash across all sampled body rows).
  Candidate V': same as V, but a column counts as "amount-bearing" if EITHER a parseable
                amount appears OR the cell is a blank/dash placeholder ('-', '‐', '', ...) —
                targets exactly the failure mode V was falsified for.
  Candidate 4:  hybrid — use the header-structural answer (candidate1 == candidate2, both
                non-abstain) when it's available and confident, else fall back to V'.

Pass bar (plan §1, T1.1): on tables where the CURRENT pipeline already computes the correct
column (no span defect present) the candidate's L must equal today's `offset` in >=99.9% of
tables. Defect tables are reported for context only; a substantive correctness call there
needs the specific 6 filings from handoff §8-2 (traced against the raw XML / DART screen
manually, not by a threshold).

Read-only. Raw XML only, no DB writes.
"""
from __future__ import annotations

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

# dash/blank placeholders DART tables use in amount columns that happen to be all-zero.
DASH_SET = {"", "-", "‐", "―", "–", "—", "ㅡ"}

# debug collector for LVs residual mismatches (see analyze_table) — populated only when
# main() turns it on via sys.argv.
DEBUG_MISS_ON = False
DEBUG_MISS: list[str] = []
DEBUG_NEG_ON = False

# handoff §8-2 case studies — raw-markup-confirmed span defects, used for eyeball checks.
CASE_STUDIES = {
    "20240814002630": "텔코웨어",
    "20220316000791": "유진증권",
    "20170814001998": "미래에셋생명",
    "20151113001035": "유비벨록스",
    "20171114002151": "POSCO",
    "20150429000186": "풍강",
}


def _cell_text(td) -> str:
    return " ".join("".join(td.itertext()).split())


def _header_split(trs):
    """Same header/body split rule as `_build_col_labels`."""
    n_header = 0
    for tr in trs:
        cells = [_cell_text(td) for td in tr]
        if len(cells) > 1 and any(_NUMBER_PATTERN.search(c) for c in cells[1:]):
            break
        n_header += 1
    return n_header


def _build_header_grid(trs, n_header):
    """Occupied-grid over header rows only — identical construction to `_build_col_labels`,
    but also records `origin[(r,c)]` = the row a cell was physically placed in (as opposed
    to a row it merely occupies via an inherited ROWSPAN from an earlier row)."""
    occupied: set[tuple[int, int]] = set()
    origin: dict[tuple[int, int], int] = {}
    grid: dict[tuple[int, int], str] = {}
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
                    origin[(r + dr, c + dc)] = r
                    if txt:
                        grid[(r + dr, c + dc)] = txt
            c += cs
    width = max((col for _, col in occupied), default=0) + 1
    return occupied, origin, grid, width


def _real_header_rows(grid, n_header, width) -> list[int]:
    """Drop CAPTION rows from the header block before running either candidate.

    A caption row is a full-width free-text line ('요약연결재무상태표상 자산', a note
    sub-heading, ...) that ends up inside the header block only because it carries no
    digits (so `_header_split` doesn't treat it as a data row) — it is NOT a per-column
    label row. Structural signature: the SAME non-empty text occupies every grid column.
    Discovered empirically (see plan T1.1 measurement log) — without this filter, both
    candidates fail on the majority of tables because a caption row breaks the vertical
    text-run (candidate 1) or gets counted as the "bottom label row" (candidate 2)."""
    if width < 2:
        return list(range(n_header))
    real = []
    for r in range(n_header):
        vals = [grid.get((r, c)) for c in range(width)]
        is_caption = bool(vals[0]) and all(v == vals[0] for v in vals)
        if not is_caption:
            real.append(r)
    return real


def candidate_1(grid, n_header, width) -> int | None:
    """Leading columns where every REAL header row (captions excluded) shows the SAME
    non-empty text (a label column carried down by a full-height ROWSPAN, e.g. '구분').

    Meaningless with fewer than 2 real header rows (any non-empty cell trivially "runs
    through" a 1-row span) -> abstain (None) rather than silently returning `width`."""
    real_rows = _real_header_rows(grid, n_header, width)
    if len(real_rows) < 2:
        return None
    L = 0
    while L < width:
        top = grid.get((real_rows[0], L))
        if not top:
            break
        if all(grid.get((r, L)) == top for r in real_rows):
            L += 1
        else:
            break
    return L


def candidate_2(grid, origin, n_header, width) -> int | None:
    """width - (columns whose BOTTOM REAL header row cell ORIGINATES there, i.e. is a
    genuine period/classification label, not an inherited ROWSPAN carry-down or a caption
    row swept up by `_header_split`)."""
    real_rows = _real_header_rows(grid, n_header, width)
    if not real_rows:
        return None
    bottom = real_rows[-1]
    n_amounts_grid = sum(1 for c in range(width) if origin.get((bottom, c)) == bottom)
    return width - n_amounts_grid


def analyze_table(table, cnt, case_label=None):
    trs = table_direct_rows(table)
    if not trs:
        return
    n_header = _header_split(trs)
    if n_header == 0 or n_header >= len(trs):
        return

    # current pipeline's offset (physical-cell-count based) — the thing we're comparing to.
    n_amounts = 0
    for tr in trs[n_header:]:
        n_amounts = max(n_amounts, max(0, len(_get_cells(tr)) - 1))
    if n_amounts == 0:
        return

    occupied, origin, grid, width = _build_header_grid(trs, n_header)
    offset = width - n_amounts
    if offset < 0:
        return

    L1 = candidate_1(grid, n_header, width)
    L2 = candidate_2(grid, origin, n_header, width)
    L3 = L1 if L1 == L2 else None

    # continue the SAME occupied/origin grid walk through body rows -> ground truth, and
    # classify this table clean/defect exactly like the census scripts do. Also collect,
    # per grid column, whether it EVER holds a parseable amount (candidate V) or a
    # parseable-amount-or-dash/blank placeholder (candidate V') anywhere in the body.
    table_defect = False
    amount_cols: set[int] = set()
    amount_cols_soft: set[int] = set()
    col_raw_samples: dict[int, list[str]] = {}
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
                    origin[(r + dr, c + dc)] = r
            c += cs
        for k in range(1, len(true_cols)):
            raw = cells_text[k] if k < len(cells_text) else ""
            is_amount = parse_amount(raw, 1) is not None
            if is_amount:
                amount_cols.add(true_cols[k])
                amount_cols_soft.add(true_cols[k])
            elif raw.strip() in DASH_SET:
                amount_cols_soft.add(true_cols[k])
            if (DEBUG_MISS_ON or DEBUG_NEG_ON) and raw.strip():
                col_raw_samples.setdefault(true_cols[k], []).append(raw)
            if not is_amount:
                continue
            if true_cols[k] != offset + (k - 1):
                table_defect = True

    def leading_non_amount(cols: set[int]) -> int:
        L = 0
        while L < width and L not in cols:
            L += 1
        return L

    LV = leading_non_amount(amount_cols) if amount_cols else None
    LVs = leading_non_amount(amount_cols_soft) if amount_cols_soft else None
    L4 = L1 if (L1 is not None and L1 == L2) else LVs

    # debug: for clean tables where LVs still misses, dump the raw text sitting in the
    # "should be amount" columns [min(LVs,offset), max(LVs,offset)) that defeated both
    # amount-type checks — captured from the single walk above, no grid re-walk needed.
    if DEBUG_MISS_ON and not table_defect and LVs is not None and LVs != offset \
            and len(DEBUG_MISS) < 500:
        missed_cols = set(range(min(LVs, offset), max(LVs, offset)))
        for col in missed_cols:
            for raw in col_raw_samples.get(col, [])[:5]:
                DEBUG_MISS.append(repr(raw))

    bucket = "defect" if table_defect else "clean"
    hbucket = "nh1" if n_header == 1 else ("nh2" if n_header == 2 else "nh3p")
    cnt[f"{bucket}_tables"] += 1
    cnt[f"{bucket}_{hbucket}_tables"] += 1
    for name, L in (("L1", L1), ("L2", L2), ("L3", L3), ("LV", LV), ("LVs", LVs), ("L4", L4)):
        for scope in (bucket, f"{bucket}_{hbucket}"):
            if L is None:
                cnt[f"{scope}_{name}_abstain"] += 1
            elif L == offset:
                cnt[f"{scope}_{name}_eq"] += 1
            else:
                cnt[f"{scope}_{name}_ne"] += 1
        if L is not None and L != offset:
            cnt[f"{bucket}_{name}_delta{L - offset:+d}"] += 1

    if DEBUG_NEG_ON and not table_defect and LVs is not None and LVs < offset:
        print(f"\n### NEGATIVE-DELTA case: LVs={LVs} < offset={offset} "
              f"(n_header={n_header} width={width}) ###")
        for r in range(n_header):
            print(f"  header row {r}: {[grid.get((r, c), '') for c in range(width)]}")
        for col in range(LVs, offset):
            print(f"  col {col} raw samples: {col_raw_samples.get(col, [])[:8]}")

    if case_label:
        print(f"\n--- case study: {case_label} (n_header={n_header} width={width} "
              f"offset(current)={offset} n_amounts(physical)={n_amounts}) ---")
        for r in range(n_header):
            row_txt = [grid.get((r, c), "") for c in range(width)]
            print(f"  header row {r}: {row_txt}")
        print(f"  candidate L1 (vertical-run label col) = {L1}")
        print(f"  candidate L2 (bottom-row-originating)  = {L2}")
        print(f"  candidate L3 (intersection)            = {L3}")
        print(f"  candidate LV (value-based)             = {LV}")
        print(f"  candidate LV' (value-based + dash)     = {LVs}")
        print(f"  candidate L4 (hybrid)                  = {L4}")
        print(f"  table classified                       = {bucket}")


def main():
    global DEBUG_MISS_ON, DEBUG_NEG_ON
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    DEBUG_MISS_ON = "--debug-miss" in sys.argv
    DEBUG_NEG_ON = "--debug-neg" in sys.argv
    random.seed(20260807)
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
    pool = [(r, paths[r]) for r in rcepts if paths.get(r)]
    sample = random.sample(pool, min(n, len(pool)))

    # make sure the known case-study filings are included even if the random sample misses them.
    case_pool = [(r, paths[r]) for r in CASE_STUDIES if paths.get(r)]
    sample_rcepts = {r for r, _ in sample}
    for r, fp in case_pool:
        if r not in sample_rcepts:
            sample.append((r, fp))

    cnt = Counter()
    n_err = 0
    for rcept, fp in sample:
        try:
            root = _parse_xml_file(Path(fp))
        except Exception:
            n_err += 1
            continue
        if root is None:
            n_err += 1
            continue
        secs = assign_note_tables_with_titles(root)
        case_label = CASE_STUDIES.get(rcept)
        table_i = 0
        for sk in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for table, _t in secs.get(sk, []):
                if _table_has_data_rows(table, minimum=1):
                    table_i += 1
                    label = f"{case_label} {rcept} table#{table_i}" if case_label else None
                    analyze_table(table, cnt, case_label=label)

    print("\n" + "=" * 70)
    print(f"filings sampled {len(sample)} (parse errors {n_err})")
    for b in ("clean", "defect"):
        tot = cnt[f"{b}_tables"]
        print(f"\n{b.upper()} tables: {tot:,}")
        if tot == 0:
            continue
        for scope_label, scope in (
            ("ALL", b),
            ("  n_header==1", f"{b}_nh1"),
            ("  n_header==2", f"{b}_nh2"),
            ("  n_header>=3", f"{b}_nh3p"),
        ):
            stot = cnt[f"{scope}_tables"] if scope != b else tot
            if scope != b and stot == 0:
                continue
            print(f" {scope_label} ({stot:,} tables)")
            for name in ("L1", "L2", "L3", "LV", "LVs", "L4"):
                eq = cnt[f"{scope}_{name}_eq"]
                ne = cnt[f"{scope}_{name}_ne"]
                ab = cnt[f"{scope}_{name}_abstain"]
                print(f"    {name}: L==offset {eq:>7,} ({eq/stot*100:5.1f}%)  "
                      f"L!=offset {ne:>7,} ({ne/stot*100:5.1f}%)  "
                      f"abstain {ab:>7,} ({ab/stot*100:5.1f}%)")
        deltas_hdr_printed = False
        for name in ("L1", "L2", "L3", "LV", "LVs", "L4"):
            deltas = sorted((k, v) for k, v in cnt.items()
                             if k.startswith(f"{b}_{name}_delta"))
            if deltas:
                if not deltas_hdr_printed:
                    print(" deltas (L != offset, ALL n_header):")
                    deltas_hdr_printed = True
                print(f"    {name}: " + "  ".join(
                    f"{k.split('delta')[1]}:{v:,}" for k, v in deltas))

    print("\nPASS BAR (plan §1, T1.1): on CLEAN tables, candidate L==offset must be >= 99.9%.")
    for name in ("L1", "L2", "L3", "LV", "LVs", "L4"):
        tot = cnt["clean_tables"] or 1
        rate = cnt[f"clean_{name}_eq"] / tot * 100
        verdict = "PASS" if rate >= 99.9 else "FAIL"
        print(f"  {name}: {rate:.2f}%  -> {verdict}")

    if DEBUG_MISS_ON:
        print(f"\nDEBUG: raw text sitting in LVs-missed 'should be amount' columns "
              f"({len(DEBUG_MISS)} samples):")
        from collections import Counter as _C
        for txt, n_seen in _C(DEBUG_MISS).most_common(60):
            print(f"  {n_seen:>4}  {txt}")


if __name__ == "__main__":
    main()
