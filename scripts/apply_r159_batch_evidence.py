#!/usr/bin/env python
"""R159 batch(2026-09-23) — reload every filing touched by the batch-confirmed
`_SOURCE_TYPO_CELL_FIXES` entries in `scripts/scan_r159_batch_evidence.py`.

User instruction: "일괄 확인으로 진행해" (batch-confirm and proceed), after
reviewing that 194/463 scanned dot-typo cells carry strong evidence (twin or a
multi-component row identity) — see `docs/qa/r159_batch_evidence_2026-09-23.md`
for the full derivation + the safety filters applied.

The rcept list here is DERIVED from `_SOURCE_TYPO_CELL_FIXES` (only the keys
belonging to this batch, i.e. everything scanned by
`scripts/scan_r159_batch_evidence.py`), not hand-typed — 93 filings is too many
to hardcode reliably. Unlike the smaller one-off `apply_r*_reviewed_*.py`
scripts, this one is allowed to iterate a derived list BECAUSE the correction
values themselves were already gated by that script's safety filters (digit
length >= 5, well-formed twin grouping, identity component count >= 2, no
same-cell-different-value conflicts) and the whole batch was approved by name
by the user as one decision.

Each filing is verified AFTER loading and rolled back on failure:
  1. total report_lines row count must not DECREASE
  2. for SCE specifically: no row may be left with label '0', and no row that
     already had a closable owners'-share + NCI = total identity may break

Usage:
    python scripts/apply_r159_batch_evidence.py --dry-run
    python scripts/apply_r159_batch_evidence.py --apply
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
from parser.xml.table_extractor import _SOURCE_TYPO_CELL_FIXES

_BATCH_START_RCEPT = "20150515002022"  # first key introduced by the batch pass
_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def _batch_rcepts() -> list[str]:
    """rcepts touched by THIS batch — every key added by
    `scan_r159_batch_evidence.py`. Derived from the audit doc's rcept list via
    the dict itself: all keys from `_BATCH_START_RCEPT` onward in insertion
    order (dict preserves insertion order in Python 3.7+), since the batch
    block was appended after the pre-existing manual entries.
    """
    keys = list(_SOURCE_TYPO_CELL_FIXES.keys())
    start = next(i for i, (r, _c) in enumerate(keys) if r == _BATCH_START_RCEPT)
    seen = []
    for r, _c in keys[start:]:
        if r not in seen:
            seen.append(r)
    return seen


def _concept(col_label: str) -> str:
    return re.sub(r"\s+", "", (col_label or "").split(">")[-1])


def _sce_state(session, rcept_no: str) -> tuple[int, int, int]:
    """(SCE logical rows, SCE cells, rows failing their own additive identity)."""
    rows = session.execute(text("""
        SELECT row_order, basis, label_raw, col_label, value_won
        FROM report_lines
        WHERE rcept_no = :r AND statement='SCE'"""),
        {"r": rcept_no}).mappings().all()
    by_row: dict = {}
    zero_label = 0
    for r in rows:
        key = (r["basis"], r["row_order"])
        by_row.setdefault(key, {})[_concept(r["col_label"])] = r["value_won"]
        if (r["label_raw"] or "").strip() == "0":
            zero_label += 1
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
    return len(by_row), zero_label, broken


def _total_rows(session, rcept_no: str) -> int:
    return session.execute(text(
        "SELECT count(*) FROM report_lines WHERE rcept_no = :r"),
        {"r": rcept_no}).scalar()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rcepts = _batch_rcepts()
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
            before_total = _total_rows(session, rcept_no)
            before_sce = _sce_state(session, rcept_no)
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
            print("%s  %-20s status=%s  before: rows=%d sce_label0=%d "
                  "sce_broken=%d" % (
                      rcept_no, m["corp_name"][:20], m["status"],
                      before_total, before_sce[1], before_sce[2]))
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
            after_total = _total_rows(session, rcept_no)
            after_sce = _sce_state(session, rcept_no)
            problems = []
            if after_total < before_total:
                problems.append("total rows DECREASED %d -> %d" % (
                    before_total, after_total))
            if after_sce[1] > before_sce[1]:
                problems.append("SCE label '0' rows increased %d -> %d" % (
                    before_sce[1], after_sce[1]))
            if after_sce[2] > before_sce[2]:
                problems.append("SCE broken identities increased %d -> %d" % (
                    before_sce[2], after_sce[2]))
            if problems:
                session.rollback()
                print("   ROLLED BACK — %s" % "; ".join(problems))
                blocked += 1
                continue
            session.commit()
            ok += 1
            print("   OK  after: rows=%d sce_label0=%d sce_broken=%d" % (
                after_total, after_sce[1], after_sce[2]))

    if args.apply:
        print("\n적재 %d · 보호됨/실패 %d · 메타없음/추출실패 %d / 전체 %d" % (
            ok, blocked, skipped, len(rcepts)))
    else:
        print("\n(dry-run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
