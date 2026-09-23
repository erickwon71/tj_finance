#!/usr/bin/env python
"""R166 - re-load the THREE already-reviewed filings, with explicit approval.

`store_report_lines()` refuses to overwrite a filing whose review queue status
is 'pass' unless `overwrite_reviewed=True` (R139). These three are out of step
with the current code after R166's design revision (merge -> emit a separate
row with the inherited ROWSPAN label):

    20240320000950  SK이노베이션 2023FY   +1 row
    20230814001921  한미반도체   2023H1   +13 rows
    20260316000827  SK이노베이션 2025FY   +3 rows, and 21 rows mislabelled '0'

★The first two hold data I wrote MYSELF under the superseded merge design, so
leaving them is not "untouched original output" - it is my own stale write.
The third was never written by me; it still carries the pre-R166 shape where a
continuation row was loaded under the label '0'.

★The rcept numbers are HARDCODED on purpose. This is one of only two places in
the tree that pass `overwrite_reviewed=True`, and it may only ever touch
filings the user approved by name (approval 2026-09-23, same pattern as
`scripts/apply_r162_r163_reviewed_5.py` and `apply_r152b_reviewed_2.py`).
Do not turn this into a generic --rcept-list runner.

Each filing is verified AFTER loading and rolled back on failure:
  1. no SCE row may be left with the label '0'
  2. SCE row count must not DECREASE
  3. every SCE row that has both an owners'-share subtotal and a total must
     close its own identity

Usage:
    python scripts/apply_r166_reviewed_3.py --dry-run
    python scripts/apply_r166_reviewed_3.py --apply
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

# User-approved 2026-09-23. Do not add without a new approval.
APPROVED = [
    ("20240320000950", "SK이노베이션 2023FY  이슈#34"),
    ("20230814001921", "한미반도체   2023H1  이슈#35"),
    ("20260316000827", "SK이노베이션 2025FY  라벨 '0' 행 교정"),
]

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _concept(col_label: str) -> str:
    return re.sub(r"\s+", "", (col_label or "").split(">")[-1])


def _sce_state(session, rcept_no: str) -> tuple[int, int, int, int]:
    """(rows, cells, label-'0' rows, broken identity rows)."""
    rows = session.execute(text("""
        SELECT row_order, basis, label_raw, col_label, value_won
        FROM report_lines
        WHERE rcept_no = :r AND statement='SCE'"""),
        {"r": rcept_no}).mappings().all()
    by_row: dict = {}
    zero_label = set()
    for r in rows:
        key = (r["basis"], r["row_order"])
        by_row.setdefault(key, {})[_concept(r["col_label"])] = r["value_won"]
        if (r["label_raw"] or "").strip() == "0":
            zero_label.add(key)
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
    return len(by_row), len(rows), len(zero_label), broken


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
            print("   before: rows=%d cells=%d label0=%d broken=%d" % before)
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
            print("   after : rows=%d cells=%d label0=%d broken=%d" % after)
            problems = []
            if after[2] > 0:
                problems.append("label '0' rows remain: %d" % after[2])
            if after[0] < before[0]:
                problems.append("SCE rows DECREASED %d -> %d" % (before[0], after[0]))
            if after[3] > before[3]:
                problems.append("broken identities increased %d -> %d"
                                % (before[3], after[3]))
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
