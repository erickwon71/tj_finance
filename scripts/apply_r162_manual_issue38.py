#!/usr/bin/env python
"""R162-manual — reload the ONE filing camp_run reported as issue#38, user-approved
2026-09-23: SK텔레콤 00159023 `20210517001554`(2021Q1) [별도] SCE `2021.03.31
(기말자본)` 자기주식 sign.

★The rcept is HARDCODED on purpose — same pattern as `apply_r158_dot_typo_
confirmed.py` / `apply_r166_reviewed_3.py`. Do not add entries here without a
new approval; add the correction to
`fin2/extract/sce_sign_repair.py::_MANUAL_SIGN_FIXES` first.

Usage:
    python scripts/apply_r162_manual_issue38.py --dry-run
    python scripts/apply_r162_manual_issue38.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (
    extract_report_lines, store_report_lines, store_report_tables)

RCEPT = "20210517001554"
_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _self_check(session, rcept_no: str) -> tuple:
    row = session.execute(text("""
        SELECT value_won FROM report_lines
        WHERE rcept_no=:r AND statement='SCE' AND basis='separate'
          AND row_order=17 AND col_label LIKE '%자기주식%'"""),
        {"r": rcept_no}).mappings().first()
    total = session.execute(text(
        "SELECT count(*) FROM report_lines WHERE rcept_no=:r"),
        {"r": rcept_no}).scalar()
    return (row["value_won"] if row else None, total)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        m = session.execute(text("""
            SELECT dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
                   q.status
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            LEFT JOIN layer2_review_queue q ON q.rcept_no = dt.rcept_no
            WHERE dt.rcept_no = :r AND dt.file_type='xml'"""),
            {"r": RCEPT}).mappings().first()
        if not m:
            print("! no metadata for %s" % RCEPT)
            return 1
        before_val, before_total = _self_check(session, RCEPT)
        path = Path(_SD + m["file_path"][len(_LINK):]
                    if m["file_path"].startswith(_LINK) else m["file_path"])
        lines = extract_report_lines(
            path, rcept_no=RCEPT, corp_code=m["corp_code"],
            report_fiscal_year=m["fiscal_year"],
            report_fiscal_period=m["fiscal_period"])
        print("status=%s  before: 자기주식=%s total_rows=%d" % (
            m["status"], f"{before_val:,}" if before_val is not None else None,
            before_total))
        if not args.apply:
            return 0
        store_report_lines(session, RCEPT, lines,
                           overwrite_reviewed=(m["status"] == "pass"))
        store_report_tables(session, RCEPT, lines)
        session.flush()
        after_val, after_total = _self_check(session, RCEPT)
        problems = []
        if after_total < before_total:
            problems.append("total rows DECREASED %d -> %d" % (
                before_total, after_total))
        if after_val != -2_169_660_000_000:
            problems.append("자기주식 값이 기대값이 아님: %s" % after_val)
        if problems:
            session.rollback()
            print("ROLLED BACK — %s" % "; ".join(problems))
            return 1
        session.commit()
        print("OK  after: 자기주식=%s total_rows=%d" % (
            f"{after_val:,}", after_total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
