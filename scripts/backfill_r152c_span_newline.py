#!/usr/bin/env python
"""R152-c retroactive backfill — reload every filing
`scripts/scan_r152c_span_newline_scope.py` found still missing a compacted
대손준비금/비상위험준비금 supplementary row that current code can now recover
(camp_run 이슈#41, 2026-09-23).

The code fix (`_first_of_compacted_supplementary_cell` rejoining a first-number
token split by a `<SPAN>`-boundary newline) already ships in
`parser/xml/table_extractor.py`. This script is step ② of the runbook — the
code fix alone does not touch historically-loaded rows.

★Unlike R152/R152-b, this scope (171 filings, all financial-sector BS/IS rows
using the compacted supplementary format) is backfilled directly rather than
left to natural reload cycles — the scan already narrowed the population to
exactly the filings where a fresh extraction recovers a row the current DB is
missing, so there is no guesswork about scope.

Each filing is verified AFTER loading and rolled back on failure:
  1. total report_lines row count must not DECREASE
  2. rows whose label matches 대손준비금/비상위험준비금 must not DECREASE

Usage:
    python scripts/backfill_r152c_span_newline.py --dry-run
    python scripts/backfill_r152c_span_newline.py --apply
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

_AFFECTED = Path(__file__).resolve().parents[1] / \
    "docs/qa/r152c_affected_2026-09-24.txt"
_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _state(session, rcept_no: str) -> tuple:
    total = session.execute(text(
        "SELECT count(*) FROM report_lines WHERE rcept_no=:r"),
        {"r": rcept_no}).scalar()
    reserve_rows = session.execute(text("""
        SELECT count(*) FROM report_lines
        WHERE rcept_no=:r AND col_index=0
          AND label_raw ~ '대손준비금|비상위험준비금'"""),
        {"r": rcept_no}).scalar()
    return total, reserve_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rcepts = [r.strip() for r in _AFFECTED.read_text().splitlines() if r.strip()]
    print(f"대상 필링 {len(rcepts)}건\n")

    ok = skipped = blocked = 0
    with get_session() as session:
        for rcept_no in rcepts:
            m = session.execute(text("""
                SELECT dt.file_path, f.corp_code, f.corp_name, f.fiscal_year,
                       f.fiscal_period, q.status
                FROM download_tasks dt JOIN filings f USING (rcept_no)
                LEFT JOIN layer2_review_queue q ON q.rcept_no = dt.rcept_no
                WHERE dt.rcept_no = :r AND dt.file_type='xml'"""),
                {"r": rcept_no}).mappings().first()
            if not m:
                print("! %s: no metadata" % rcept_no)
                skipped += 1
                continue
            before_total, before_reserve = _state(session, rcept_no)
            path = Path(_SD + m["file_path"][len(_LINK):]
                        if m["file_path"].startswith(_LINK) else m["file_path"])
            try:
                lines = extract_report_lines(
                    path, rcept_no=rcept_no, corp_code=m["corp_code"],
                    report_fiscal_year=m["fiscal_year"],
                    report_fiscal_period=m["fiscal_period"])
            except Exception as exc:                     # noqa: BLE001
                print("! %s %s: extract FAILED %s" % (
                    rcept_no, m["corp_name"], exc))
                skipped += 1
                continue
            if not lines:
                print("! %s %s: extracted 0 rows" % (rcept_no, m["corp_name"]))
                skipped += 1
                continue
            print("%s  %-16s status=%s  before: rows=%d reserve=%d" % (
                rcept_no, m["corp_name"][:16], m["status"], before_total,
                before_reserve))
            if not args.apply:
                continue
            overwrite = m["status"] == "pass"
            try:
                store_report_lines(session, rcept_no, lines,
                                   overwrite_reviewed=overwrite)
                store_report_tables(session, rcept_no, lines)
                session.flush()
            except Exception as exc:                     # noqa: BLE001
                session.rollback()
                print("   FAILED: %s" % exc)
                skipped += 1
                continue
            after_total, after_reserve = _state(session, rcept_no)
            problems = []
            if after_total < before_total:
                problems.append("total rows DECREASED %d -> %d" % (
                    before_total, after_total))
            if after_reserve < before_reserve:
                problems.append("reserve rows DECREASED %d -> %d" % (
                    before_reserve, after_reserve))
            if problems:
                session.rollback()
                print("   ROLLED BACK — %s" % "; ".join(problems))
                blocked += 1
                continue
            session.commit()
            ok += 1
            print("   OK  after: rows=%d reserve=%d" % (after_total, after_reserve))

    if args.apply:
        print("\n적재 %d · 보호됨/실패 %d · 메타없음/추출실패 %d / 전체 %d" % (
            ok, blocked, skipped, len(rcepts)))
    else:
        print("\n(dry-run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
