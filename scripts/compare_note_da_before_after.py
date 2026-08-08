"""T3.6 — compare note_da_canonicals() BEFORE (current DB, pre-backfill, pre-fix note_lines)
vs AFTER (re-parse raw XML with the fixed extract_report_lines() code path, in-memory, no DB
writes) for a sample of filings.

Note: `note_da_canonicals()` reads straight from the `note_lines`/`report_tables` tables, which
still hold the pre-fix (R11) column assignment because Phase 4 (full backfill) has not run yet.
To see what D&A canonicals the FIXED code would produce, we call
`extract_report_lines(..., include_notes=True)` directly (production code, already includes the
Phase 2 fix) and feed the resulting note lines into the newly-split
`_note_da_canonicals_from_rows()` core function — without touching the DB.

A changed result is EXPECTED to be common (period assignment for note rows depends on col_index/
col_label, which is exactly what R11 fixes) — see docs/plans/note_span_fix_plan_2026-08-07.md
T3.6. This script only measures how often it changes; verifying each change against the source
document is a separate manual step.

Read-only. Does not touch the DB pipeline.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import get_session
from sqlalchemy import text

from fin2.extract.report_lines import extract_report_lines
from fin2.layer3.note_da import note_da_canonicals, _note_da_canonicals_from_rows

KNOWN_CORPS = {
    "00155373": "풍강", "00592653": "유비벨록스", "00112332": "미래에셋생명",
    "00155319": "POSCO홀딩스", "00131054": "유진증권", "00361488": "텔코웨어",
    # from memory: known note-sourced D&A users
    "00164742": "현대차", "00877059": "셀트리온", "01515323": "에코프로",
}


def after_canonicals_both_bases(file_path, rcept_no, corp_code, fy, period):
    """Parses the filing ONCE and returns {basis: canonicals} for both bases."""
    lines = extract_report_lines(
        Path(file_path), rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=fy, report_fiscal_period=period, include_notes=True,
    )
    out = {}
    for basis in ("consolidated", "separate"):
        rows = [l for l in lines if l.statement == "note" and l.basis == basis
                and l.header_hint is None and l.value_won is not None]
        out[basis] = _note_da_canonicals_from_rows(rows, period) if rows else {}
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    random.seed(20260808)

    with get_session() as s:
        # GROUP BY rcept_no (not DISTINCT on the full tuple) — much cheaper on a 245M-row
        # table, and (corp_code, fy, period) are functionally dependent on rcept_no anyway.
        base = s.execute(text(
            """
            SELECT rcept_no, min(corp_code), min(report_fiscal_year),
                   min(report_fiscal_period)
            FROM note_lines
            WHERE report_fiscal_period IN ('FY','H1','Q1','Q3')
            GROUP BY rcept_no
            """
        )).fetchall()
        rcepts = [r[0] for r in base]
        paths = dict(s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
        rows = [(r, c, fy, p, paths[r]) for r, c, fy, p in base if paths.get(r)]
    pool = [tuple(r) for r in rows]
    print(f"population with note_lines: {len(pool)}", flush=True)

    known = [r for r in pool if r[1] in KNOWN_CORPS]
    rest = [r for r in pool if r[1] not in KNOWN_CORPS]
    sample = known + random.sample(rest, min(n, len(rest)))
    print(f"sample: {len(sample)} ({len(known)} known + {len(sample)-len(known)} random)",
          flush=True)

    n_checked = 0
    n_changed = 0
    n_errors = 0
    changed = []
    with get_session() as s:
        for i, (rcept, corp, fy, period, fp) in enumerate(sample):
            try:
                after_both = after_canonicals_both_bases(fp, rcept, corp, fy, period)
            except Exception as e:
                n_errors += 2
                if n_errors <= 20:
                    print(f"  ERROR {rcept}: {type(e).__name__}: {e}", flush=True)
                continue
            for basis in ("consolidated", "separate"):
                n_checked += 1
                before = note_da_canonicals(s, rcept, basis, period)
                after = after_both[basis]
                if before != after:
                    n_changed += 1
                    changed.append((rcept, corp, fy, period, basis, before, after))
            if (i + 1) % 100 == 0:
                print(f"...{i+1}/{len(sample)}  changed={n_changed}  errors={n_errors}",
                      flush=True)

    print("=" * 70)
    print(f"filing x basis checked : {n_checked}")
    print(f"errors                 : {n_errors}")
    print(f"changed (before!=after): {n_changed} ({n_changed/max(1,n_checked)*100:.2f}%)")
    print("=" * 70)
    for rcept, corp, fy, period, basis, before, after in changed[:60]:
        tag = KNOWN_CORPS.get(corp, "")
        print(f"\n{rcept} corp={corp}{(' '+tag) if tag else ''} fy={fy} {period} {basis}")
        print(f"  BEFORE (DB, pre-fix)   : {before}")
        print(f"  AFTER  (re-parse, fix) : {after}")


if __name__ == "__main__":
    main()
