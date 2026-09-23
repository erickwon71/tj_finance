#!/usr/bin/env python
"""R158 — reload filings whose dot-typo cells the USER confirmed against the
DART original, one at a time, from `docs/qa/dot_typo_needs_dart_2026-09-23.md`.

Each entry here first needs a matching fix registered in
`parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES` (the actual value
correction). This script only handles the RELOAD: `store_report_lines()`
refuses to overwrite a filing whose review queue status is 'pass' unless
`overwrite_reviewed=True` (R139), so a plain re-run of the daily pipeline
would silently skip these.

★The rcept numbers are HARDCODED on purpose. This is one of the few places in
the tree that pass `overwrite_reviewed=True`, and it may only ever touch
filings the user approved by name (same pattern as
`scripts/apply_r166_reviewed_3.py`, `apply_r152b_reviewed_2.py`,
`apply_r162_r163_reviewed_5.py`). Do not turn this into a generic
--rcept-list runner, and do not add an entry without a matching approval.

Each filing is verified AFTER loading and rolled back on failure:
  1. SCE row count must not DECREASE
  2. every SCE row that has both an owners'-share subtotal (or per-basis
     total) and a grand total must close its own additive identity, and the
     number of rows that fail to close must not INCREASE

Usage:
    python scripts/apply_r158_dot_typo_confirmed.py --dry-run
    python scripts/apply_r158_dot_typo_confirmed.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (
    extract_report_lines, store_report_lines, store_report_tables)

# User-approved via DART screenshot/original comparison. One line per filing.
APPROVED = [
    ("20250515002500",
     "HD한국조선해양 2025Q1  연결SCE 비지배지분 3셀 — 콤마오타 확정 2026-09-23"),
    ("20250318001131",
     "HD한국조선해양 2024FY  연결SCE 비지배지분 1셀 — 2단계 항등식으로 확정 2026-09-23"),
]

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _concept(col_label: str) -> str:
    return re.sub(r"\s+", "", (col_label or "").split(">")[-1])


def _sce_state(session, rcept_no: str) -> tuple[int, int, int]:
    """(logical rows, cells, rows whose own additive identity fails to close)."""
    rows = session.execute(text("""
        SELECT row_order, basis, col_label, value_won
        FROM report_lines
        WHERE rcept_no = :r AND statement='SCE'"""),
        {"r": rcept_no}).mappings().all()
    by_row: dict = {}
    for r in rows:
        key = (r["basis"], r["row_order"])
        by_row.setdefault(key, {})[_concept(r["col_label"])] = r["value_won"]
    broken = 0
    for cols in by_row.values():
        own = next((v for k, v in cols.items()
                    if ("귀속" in k or "지배기업" in k) and "합계" in k), None)
        nci = next((v for k, v in cols.items() if "비지배" in k), None)
        tot = next((v for k, v in cols.items()
                    if k.endswith("합계") and "지배기업" not in k
                    and "귀속" not in k), None)
        if None not in (own, nci, tot) and own + nci != tot:
            broken += 1
    return len(by_row), len(rows), broken


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ok = 0
    with get_session() as session:
        for rcept_no, what in APPROVED:
            m = session.execute(text("""
                SELECT dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
                       q.status
                FROM download_tasks dt JOIN filings f USING (rcept_no)
                LEFT JOIN layer2_review_queue q ON q.rcept_no = dt.rcept_no
                WHERE dt.rcept_no = :r AND dt.file_type='xml'"""),
                {"r": rcept_no}).mappings().first()
            if not m:
                print("! %s: no metadata" % rcept_no)
                continue
            before = _sce_state(session, rcept_no)
            path = Path(_SD + m["file_path"][len(_LINK):]
                        if m["file_path"].startswith(_LINK) else m["file_path"])
            lines = extract_report_lines(
                path, rcept_no=rcept_no, corp_code=m["corp_code"],
                report_fiscal_year=m["fiscal_year"],
                report_fiscal_period=m["fiscal_period"])
            if not lines:
                print("! %s: extracted 0 rows" % rcept_no)
                continue
            print("%s  %s  status=%s" % (rcept_no, what, m["status"]))
            print("   before: rows=%d cells=%d broken=%d" % before)
            if not args.apply:
                continue
            try:
                store_report_lines(session, rcept_no, lines,
                                   overwrite_reviewed=True)
                store_report_tables(session, rcept_no, lines)
                session.flush()
            except Exception as exc:                    # noqa: BLE001
                session.rollback()
                print("   FAILED: %s" % exc)
                continue
            after = _sce_state(session, rcept_no)
            print("   after : rows=%d cells=%d broken=%d" % after)
            problems = []
            if after[0] < before[0]:
                problems.append("SCE rows DECREASED %d -> %d" % (before[0], after[0]))
            if after[2] > before[2]:
                problems.append("broken identities increased %d -> %d"
                                % (before[2], after[2]))
            if problems:
                session.rollback()
                print("   ROLLED BACK — %s" % "; ".join(problems))
                continue
            session.commit()
            ok += 1
            print("   OK")

    if args.apply:
        print("\napplied: %d / %d" % (ok, len(APPROVED)))
    else:
        print("\n(dry-run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
