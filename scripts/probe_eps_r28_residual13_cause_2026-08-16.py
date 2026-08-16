"""
R28 follow-up track T1 -- why does the main pass drop the 13 residual curated rows?
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §2-2.)

This consolidates the three scratchpad probes that produced the §2-2 verdicts. Each
answers a different question, so all three modes are kept:

  --mode gates   Re-parse the source XML and walk the exact gate sequence
                 `extract_rows` applies (header rule -> FS-title row ->
                 `_split_label_amounts` -> empty label), reporting cell-level detail
                 and whether the row survives `extract_rows`.
                 Result 2026-08-16: it DOES survive -- which is what disproved the
                 original "extract_rows drops the physical last row" hypothesis.

  --mode run     Run the real `extract_report_lines` and report whether the row is
                 emitted at all, and at which basis/table_seq/col_index.
                 Result: 6 keys ARE emitted, but only at col_index=1, so
                 `store_report_lines`'s `_is_loadable()` (current period / col 0 only)
                 keeps them out of the DB.  -> group A

  --mode trace   Monkeypatch `extract_rows` inside `fin2.extract.report_lines` to log
                 the row's parsed `amounts` vs `raw_amounts` as the main loop sees it.
                 Result: for group B1 the raw cell holds a real number but `amounts`
                 is None -- `parse_amount` rejected it because the table's multiplier
                 (x1,000,000) pushed the value past `_AMOUNT_SANE_MAX` (1e16).  For
                 group B2 the amount cells are empty strings to begin with.

Group assignment measured 2026-08-16 (design doc §2-1 table):
  A  (col_index>=1, filtered at load): 20031114000665 20031114001721 20031202000019
                                       20040619000015 20041115000296 20051111000339
  B1 (unit over-scale -> parse_amount None): 20000628000052 20070814001744 20071114000033
  B2 (amount cells empty, unexplained):      20020330000386 20060512002144
                                             20070330001121 20070814000766

Usage:
  .venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode gates
  .venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode run
  .venv/bin/python scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode trace
  # optionally restrict to some rcept_no:
  ... --mode run --rcept 20000628000052,20070814001744
"""
import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from lxml import etree                                          # noqa: E402
from sqlalchemy import text                                     # noqa: E402

from collector.db import get_session                            # noqa: E402
import fin2.extract.report_lines as rl                          # noqa: E402
from parser.xml.section_detector import table_direct_rows       # noqa: E402
from parser.xml.table_extractor import (                        # noqa: E402
    _get_cells, _header_rule_name, _is_fs_title_row, _split_label_amounts,
    _table_has_comma_note_column, extract_rows,
)

RESIDUAL = os.path.join(_REPO_ROOT, "scripts", "eps_r28_residual13_2026-08-16.json")

# How many normalized leading chars identify a row. The DB `label_raw` is the merged
# label `_split_label_amounts` produces, which is not always byte-identical to the raw
# first cell (cells get joined), so matching on a prefix of the normalized string is
# the reliable join -- an exact match silently finds nothing.
HEAD = 25


def norm(s: str) -> str:
    return " ".join((s or "").split())


def load_keys(rcept_filter):
    if not os.path.exists(RESIDUAL):
        sys.exit(f"{RESIDUAL} not found -- run "
                 "scripts/probe_eps_r28_residual13_2026-08-16.py first")
    with open(RESIDUAL, encoding="utf-8") as f:
        keys = [tuple(k) for k in json.load(f)]
    if rcept_filter:
        want = {r.strip() for r in rcept_filter.split(",") if r.strip()}
        keys = [k for k in keys if k[0] in want]
    return keys


def load_paths(rcepts):
    with get_session() as s:
        rows = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            WHERE dt.rcept_no = ANY(:r) AND dt.file_type='xml'
              AND dt.status='completed' AND dt.file_path IS NOT NULL
        """), {"r": list(rcepts)}).fetchall()
    return {r.rcept_no: r for r in rows}


def banner(k, meta):
    rcept, stmt, basis, tseq, label = k
    print("=" * 100)
    print(f"{rcept}  {stmt}/{basis}  table_seq={tseq}  "
          f"corp={meta.corp_code if meta else '?'}  "
          f"{meta.fiscal_year if meta else '?'}{meta.fiscal_period if meta else ''}")
    print(f"  label[:90] = {norm(label)[:90]}")


def mode_gates(keys, paths):
    """Walk extract_rows' gate sequence on the source XML."""
    for k in keys:
        rcept, stmt, basis, tseq, label = k
        meta = paths.get(rcept)
        banner(k, meta)
        if not meta or not os.path.exists(meta.file_path):
            print("  !! xml missing")
            continue
        head = norm(label)[:HEAD]
        tree = etree.parse(meta.file_path, etree.XMLParser(recover=True, huge_tree=True))
        found = False
        for table in tree.iter("TABLE"):
            trs = table_direct_rows(table)
            if not trs:
                continue
            cell_rows = [_get_cells(tr) for tr in trs]
            has_note_col = _table_has_comma_note_column(cell_rows)
            for idx, cells in enumerate(cell_rows):
                if not cells:
                    continue
                lab, amt = _split_label_amounts(cells, has_note_col)
                if norm(lab)[:HEAD] != head and norm(cells[0])[:HEAD] != head:
                    continue
                found = True
                first_text = cells[0].strip()
                hint = _header_rule_name(first_text, allow_date_label=False)
                fs = _is_fs_title_row(cells)
                print(f"  physical row {idx + 1}/{len(trs)}  n_cells={len(cells)}")
                print(f"    cells = {[c[:34] for c in cells]}")
                print(f"    gate1 _header_rule_name   -> {hint!r}"
                      f"{'   << DROPPED' if hint else ''}")
                print(f"    gate2 _is_fs_title_row    -> {fs}"
                      f"{'   << DROPPED' if fs else ''}")
                print(f"    gate3 _split_label_amounts-> label={norm(lab)[:55]!r} "
                      f"n_amt={len(amt)} amt={[a[:22] for a in amt]}"
                      f"{'   << DROPPED (empty label)' if not lab else ''}")
                out = extract_rows(table, multiplier=1, num_cols=3,
                                   direct_only=True, skip_junk=False)
                survived = [r for r in out if norm(r.account_name)[:HEAD] == head]
                print(f"    extract_rows -> {len(out)} rows / {len(trs)} TRs; "
                      f"row survived? {'YES' if survived else 'NO'}")
                if survived:
                    print(f"       amounts={survived[0].amounts} "
                          f"raw={survived[0].raw_amounts}")
                break
            if found:
                break
        if not found:
            print("  !! label not matched in any TABLE at this prefix length")


def mode_run(keys, paths):
    """Run the real extractor and report emission (basis/table_seq/col_index)."""
    for k in keys:
        rcept, stmt, basis, tseq, label = k
        meta = paths.get(rcept)
        banner(k, meta)
        if not meta or not os.path.exists(meta.file_path):
            print("  !! xml missing")
            continue
        head = norm(label)[:HEAD]
        lines = rl.extract_report_lines(
            meta.file_path, rcept_no=rcept, corp_code=meta.corp_code,
            report_fiscal_year=meta.fiscal_year,
            report_fiscal_period=meta.fiscal_period, include_notes=False)
        is_lines = [ln for ln in lines if ln.statement == "IS"]
        hit = [ln for ln in is_lines if norm(ln.label_raw)[:HEAD] == head]
        print(f"  extract_report_lines: total={len(lines)} IS={len(is_lines)} "
              f"key-row-emitted={len(hit)}")
        for ln in hit[:4]:
            loadable = (ln.col_index or 0) == 0
            print(f"    -> basis={ln.basis} table_seq={ln.table_seq} "
                  f"col_index={ln.col_index} value_won={ln.value_won}  "
                  f"{'LOADED' if loadable else '<< DROPPED by _is_loadable (col!=0)'}")
        if not hit:
            near = [ln for ln in is_lines
                    if "순이익" in (ln.label_raw or "")
                    and ln.basis == basis and ln.table_seq == tseq]
            print(f"    (not emitted) sibling 순이익 rows in the same table: {len(near)}")
            for ln in near[:5]:
                print(f"       {norm(ln.label_raw)[:60]!r} col={ln.col_index} "
                      f"v={ln.value_won}")


def mode_trace(keys, paths):
    """Monkeypatch extract_rows to see what the main loop received."""
    original = rl.extract_rows
    state = {"head": "", "log": []}

    def traced(*a, **kw):
        out = original(*a, **kw)
        for r in out:
            if norm(r.account_name)[:HEAD] == state["head"]:
                state["log"].append(
                    f"    reached main loop: amounts={r.amounts}\n"
                    f"                       raw_amounts={r.raw_amounts}\n"
                    f"                       num_cols={kw.get('num_cols')} "
                    f"multiplier={kw.get('multiplier')}")
        return out

    rl.extract_rows = traced
    try:
        for k in keys:
            rcept, stmt, basis, tseq, label = k
            meta = paths.get(rcept)
            banner(k, meta)
            if not meta or not os.path.exists(meta.file_path):
                print("  !! xml missing")
                continue
            state["head"] = norm(label)[:HEAD]
            state["log"] = []
            lines = rl.extract_report_lines(
                meta.file_path, rcept_no=rcept, corp_code=meta.corp_code,
                report_fiscal_year=meta.fiscal_year,
                report_fiscal_period=meta.fiscal_period, include_notes=False)
            emitted = [ln for ln in lines if norm(ln.label_raw)[:HEAD] == state["head"]]
            for line in state["log"]:
                print(line)
            if not state["log"]:
                print("    !! row never came out of extract_rows in any table")
            print(f"    emitted: {len(emitted)} "
                  f"{[(e.basis, e.table_seq, e.col_index, e.value_won) for e in emitted]}")
            # Diagnose the B1 signature: a parsable raw cell that became None.
            for line in state["log"]:
                if "amounts=[None" in line and "raw_amounts=['" in line:
                    print("    HINT: parsed None with non-empty raw -> check "
                          "parse_amount's _AMOUNT_SANE_MAX (1e16) against "
                          "raw x multiplier  (design doc §2-2 group B1 / T4)")
                    break
    finally:
        rl.extract_rows = original


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["gates", "run", "trace"])
    ap.add_argument("--rcept", help="comma-separated rcept_no subset")
    args = ap.parse_args()

    keys = load_keys(args.rcept)
    paths = load_paths({k[0] for k in keys})
    print(f"residual keys in scope: {len(keys)}\n")
    {"gates": mode_gates, "run": mode_run, "trace": mode_trace}[args.mode](keys, paths)


if __name__ == "__main__":
    main()
