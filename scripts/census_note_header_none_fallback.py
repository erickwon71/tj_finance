"""Measures a DIFFERENT defect from the one T3.1 covers: how often does
`fin2/extract/report_lines.py::_grid_header_split` fail to find a header boundary at all
(`n_header is None`, e.g. bare-year headers like "2020" that _NUMBER_PATTERN mistakes for a
data row), and — for those tables — how often does the resulting `_grid_body_rows(table,
grid_rows, 0, 0, ...)` fallback (offset hardcoded to 0) mis-assign a value cell's col_index
compared to what the PRE-FIX code (`extract_rows`, purely position-relative: first non-label
physical cell = col_idx 0) would have stored.

T3.1's census explicitly SKIPS these tables (`if n_header == 0 or n_header >= len(trs): return
0,0,0,0`), so this defect is invisible to it — found 2026-08-08 while manually verifying a T3.6
D&A before/after diff (LG에너지솔루션 20210317000676, note '31. 영업으로부터 창출된 현금',
header row literally reads "구분 | 2020" — the bare year "2020" matches _NUMBER_PATTERN so the
header row is misread as a data row, n_header lands at 0, and the None-fallback then reports the
single value column at col_index=1 instead of 0).

Read-only. Does not touch the DB.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.db import engine
from sqlalchemy import text
from concurrent.futures import ProcessPoolExecutor


def analyze_filing(fp):
    """Returns (n_tables, n_header_none, n_shifted_tables, n_shifted_values)."""
    from parser.xml.dart_xml_parser import _parse_xml_file
    from parser.xml.section_detector import assign_note_tables_with_titles, SEC_CONSOL_NOTE, SEC_SEP_NOTE
    from fin2.extract.text import _table_has_data_rows
    from fin2.extract.report_lines import _grid_header_split
    from parser.common.amount_normalizer import parse_amount

    root = _parse_xml_file(Path(fp))
    if root is None:
        return None
    sec_tables = assign_note_tables_with_titles(root)
    n_tables = n_none = n_shifted_tables = n_shifted_values = 0
    for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for table, _title in sec_tables.get(sec_kind, []):
            if not _table_has_data_rows(table, minimum=1):
                continue
            n_tables += 1
            grid_rows, n_header, offset, width = _grid_header_split(table)
            if n_header is not None:
                continue
            n_none += 1
            # Fallback path: offset forced to 0. Compare against OLD behaviour (position-
            # relative: first non-label physical cell in a row = col_idx 0, i.e. the OLD
            # code's `enumerate(row.amounts)` after dropping the label cell).
            row_shifted = False
            for row in grid_rows:
                physical = [c for c in row if not c.inherited]
                if len(physical) < 2:
                    continue
                for pos, c in enumerate(physical[1:]):   # pos = 0,1,2... = OLD col_idx
                    if parse_amount(c.text, 1) is None:
                        continue
                    new_idx = c.grid_col - 0              # NEW fallback col_idx (offset=0)
                    if new_idx != pos:
                        n_shifted_values += 1
                        row_shifted = True
            if row_shifted:
                n_shifted_tables += 1
    return n_tables, n_none, n_shifted_tables, n_shifted_values


def work(fp):
    try:
        res = analyze_filing(fp)
        if res is None:
            return ("err", 0, 0, 0, 0)
        return ("ok",) + res
    except Exception:
        return ("err", 0, 0, 0, 0)


if __name__ == "__main__":
    t0 = time.time()
    with engine.connect() as conn:
        rcepts = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()]
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
    fps = [paths[r] for r in rcepts if paths.get(r)]
    print(f"filings to scan: {len(fps)} (path lookup {time.time()-t0:.0f}s)", flush=True)

    n_ok = n_err = 0
    grand = [0, 0, 0, 0]  # n_tables, n_none, n_shifted_tables, n_shifted_values
    n_filings_with_shift = 0
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(work, fps, chunksize=8)):
            status = res[0]
            stats = res[1:]
            if status == "ok":
                n_ok += 1
                for k in range(4):
                    grand[k] += stats[k]
                if stats[2] > 0:
                    n_filings_with_shift += 1
            else:
                n_err += 1
            if (i + 1) % 5000 == 0:
                el = time.time() - t1
                rate = (i + 1) / el
                eta = (len(fps) - (i + 1)) / rate if rate > 0 else 0
                print(f"...{i+1}/{len(fps)} ({el:.0f}s, {rate:.1f}/s, eta {eta/60:.1f}min) "
                      f"ok={n_ok} err={n_err} tables={grand[0]} header_none={grand[1]} "
                      f"shifted_tables={grand[2]} shifted_values={grand[3]}", flush=True)

    print("=" * 70)
    print(f"total filings                : {len(fps)}")
    print(f"parsed ok                    : {n_ok}")
    print(f"parse errors                 : {n_err}")
    print(f"note tables (data-gated)     : {grand[0]:,}")
    print(f"  n_header is None (fallback): {grand[1]:,} ({grand[1]/max(1,grand[0])*100:.3f}%)")
    print(f"    of which value cells shift col_index vs OLD: {grand[2]:,} tables "
          f"({grand[2]/max(1,grand[1])*100:.2f}% of fallback tables), "
          f"{grand[3]:,} value cells")
    print(f"filings with >=1 shifted table: {n_filings_with_shift:,} "
          f"({n_filings_with_shift/max(1,len(fps))*100:.2f}%)")
    print(f"elapsed total                : {time.time()-t0:.0f}s")
