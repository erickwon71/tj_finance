#!/usr/bin/env python
"""R166 retroactive backfill — reload every filing the full-corpus measurement
(`scripts/measure_r166_rowspan_continuation.py`, 104,533 filings, 2026-09-23)
found to contain a ROWSPAN-continuation trigger row.

The R166 code fix (separate-row emission, no merge) already ships in
`fin2/extract/report_lines.py::_grid_body_rows`. This script is step ② of the
runbook (`docs/runbook_new_parser_pipeline_integration.md`) — retroactive
backfill is manual; the code fix alone does not touch historically-loaded rows.

★The measurement is a pure XML-structure scan, not a DB diff — it flags every
filing whose source XML has the trigger pattern, REGARDLESS of whether that
filing has already been reloaded with the fixed code. Three of these 55 were
already reloaded and verified correct earlier (`apply_r166_reviewed_3.py`):
20240320000950, 20230814001921, 20260316000827. Reloading them again here is a
no-op (extraction is deterministic) and the self-check confirms it.

Two of the 55 are BS_C/BS_S, not SCE — `_grid_body_rows` is shared across
statements, so the same fix applies; unusual only in that R166 was framed
around SCE.

Each filing is verified AFTER loading and rolled back on failure:
  1. total report_lines row count must not DECREASE
  2. SCE rows left with label '0' must not INCREASE

Usage:
    python scripts/backfill_r166_affected.py --dry-run
    python scripts/backfill_r166_affected.py --apply
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
    "docs/qa/r166_affected_2026-09-23.txt"
_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _state(session, rcept_no: str) -> tuple:
    total = session.execute(text(
        "SELECT count(*) FROM report_lines WHERE rcept_no=:r"),
        {"r": rcept_no}).scalar()
    zero_label = session.execute(text("""
        SELECT count(*) FROM report_lines
        WHERE rcept_no=:r AND statement='SCE' AND trim(label_raw)='0'"""),
        {"r": rcept_no}).scalar()
    return total, zero_label


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
            before_total, before_zero = _state(session, rcept_no)
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
            print("%s  %-16s status=%s  before: rows=%d label0=%d" % (
                rcept_no, m["corp_name"][:16], m["status"], before_total,
                before_zero))
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
            after_total, after_zero = _state(session, rcept_no)
            problems = []
            if after_total < before_total:
                problems.append("total rows DECREASED %d -> %d" % (
                    before_total, after_total))
            if after_zero > before_zero:
                problems.append("SCE label '0' rows increased %d -> %d" % (
                    before_zero, after_zero))
            if problems:
                session.rollback()
                print("   ROLLED BACK — %s" % "; ".join(problems))
                blocked += 1
                continue
            session.commit()
            ok += 1
            print("   OK  after: rows=%d label0=%d" % (after_total, after_zero))

    if args.apply:
        print("\n적재 %d · 보호됨/실패 %d · 메타없음/추출실패 %d / 전체 %d" % (
            ok, blocked, skipped, len(rcepts)))
    else:
        print("\n(dry-run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
