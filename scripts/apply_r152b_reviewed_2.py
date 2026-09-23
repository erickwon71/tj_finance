#!/usr/bin/env python
"""R152-b - re-load the TWO already-reviewed filings, with explicit approval.

`store_report_lines()` refuses to overwrite a filing whose review queue status
is 'pass' unless `overwrite_reviewed=True` (R139). These two were passed before
R152-b existed, so their separate balance sheet is still missing one equity
component row:

    20190814002431  우리금융지주 2019H1  별도BS  4. 이익잉여금
    20191114002590  우리금융지주 2019Q3  별도BS  5. 이익잉여금

Both are the R152-b shape - the compacted supplementary-reserve cell prints the
zero supplementary figure as a dash ('623,930- (692)(692)'), the head regex
missed, the cell went missing and the row vanished.

★The rcept numbers are HARDCODED on purpose. This is the only place in the tree
that passes `overwrite_reviewed=True`, and it may only ever touch filings the
user approved by name (approval 2026-09-23, mirroring the R162/R163 precedent in
`scripts/apply_r162_r163_reviewed_5.py`). Do not turn this into a generic
--rcept-list runner: the guard exists so that a reviewer's 'pass' is not
silently overwritten in bulk.

It verifies each filing AFTER loading by the equity identity
(자본총계 = sum of the components) and rolls back that filing if it does not close.

Usage:
    python scripts/apply_r152b_reviewed_2.py --dry-run
    python scripts/apply_r152b_reviewed_2.py --apply
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

# User-approved 2026-09-23. Do not add to this list without a new approval.
APPROVED = [
    ("20190814002431", "우리금융지주 2019H1  별도BS 4. 이익잉여금"),
    ("20191114002590", "우리금융지주 2019Q3  별도BS 5. 이익잉여금"),
]

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"

_ROMAN = re.compile(r"^(?:[IVX]+|\d+)\s*[.．]")


def _equity_identity(session, rcept_no: str) -> tuple[bool, str]:
    """자본총계 == sum(components) for the separate balance sheet."""
    rows = session.execute(text("""
        SELECT row_order, label_raw, value_won FROM report_lines
        WHERE rcept_no = :r AND basis='separate' AND statement='BS'
          AND coalesce(col_index, 0) = 0
        ORDER BY row_order"""), {"r": rcept_no}).mappings().all()
    total = None
    total_at = None
    for r in rows:
        flat = re.sub(r"\s+", "", (r["label_raw"] or ""))
        if flat == "자본총계":
            total = r["value_won"]
            total_at = r["row_order"]
    if total is None:
        return False, "자본총계 행을 못 찾음"

    # ★Walk BACKWARD from 자본총계 and stop at the first 총계 row (부채총계).
    #   An earlier version pre-filtered out any label containing '부채', which
    #   removed 부채총계 itself - so the walk never found its stop mark and swept
    #   up the asset lines too (12-13 "components", identity nowhere near).
    #   The guard caught it and rolled back; the bug was in this check, not the
    #   data. Rows with no value are skipped but do not stop the walk.
    block: list = []
    for r in reversed([x for x in rows if x["row_order"] < total_at]):
        flat = re.sub(r"\s+", "", r["label_raw"] or "")
        if "총계" in flat:
            break
        if r["value_won"] is None:
            continue
        if not _ROMAN.match((r["label_raw"] or "").strip()):
            continue
        block.append(r)
    ssum = sum(r["value_won"] for r in block)
    ok = ssum == total
    detail = "sum=%s total=%s (%d components)" % (
        "{:,}".format(ssum), "{:,}".format(total), len(block))
    return ok, detail


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
                FROM download_tasks dt
                JOIN filings f USING (rcept_no)
                LEFT JOIN layer2_review_queue q ON q.rcept_no = dt.rcept_no
                WHERE dt.rcept_no = :r AND dt.file_type='xml'"""),
                {"r": rcept_no}).mappings().first()
            if not m:
                print("! %s: no metadata" % rcept_no)
                continue
            path = Path(_SD + m["file_path"][len(_LINK):]
                        if m["file_path"].startswith(_LINK) else m["file_path"])
            lines = extract_report_lines(
                path, rcept_no=rcept_no, corp_code=m["corp_code"],
                report_fiscal_year=m["fiscal_year"],
                report_fiscal_period=m["fiscal_period"])
            if not lines:
                print("! %s: extracted 0 rows" % rcept_no)
                continue
            print("%s  %s  status=%s  %d rows extracted"
                  % (rcept_no, what, m["status"], len(lines)))
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
            good, detail = _equity_identity(session, rcept_no)
            if not good:
                session.rollback()
                print("   ROLLED BACK - identity does not close: %s" % detail)
                continue
            session.commit()
            ok += 1
            print("   OK - identity closes: %s" % detail)

    if args.apply:
        print("\napplied: %d / %d" % (ok, len(APPROVED)))
    else:
        print("\n(dry-run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
