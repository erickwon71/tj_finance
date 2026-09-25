#!/usr/bin/env python
"""Live-extraction sanity check for the finalized R162-d (`repair_sce_row_identity`).

Runs `extract_report_lines()` end-to-end (real parse, not the DB-approximation scan)
on the exact filings manually verified against raw XML on 2026-09-25, and checks the
expected outcome for each: the true-positive cases should now be flipped, the
false-positive (OCI remeasurement, cross-basis-only, non-capital-transaction label)
must NOT be touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

TARGETS = [
    # 2026-09-25 최초 표본대조 때는 SCE 원문표만 보고 "오탐"이라 판단했으나, IS 문(별도
    # basis 자체)에 같은 개념('확정급여제도의 재측정손익')이 -20,975,944 로 이미 있어
    # (R162 이 이걸로 이익잉여금 칸을 이미 확정) — 사실은 같은-basis IS 앵커가 있는
    # 참(true positive)이었다. DB 는 그 열을 아직 못 뽑은 구버전이라 이 앵커가 없다 —
    # 재추출하면 잡힌다(r162d_row_identity_handoff_2026-09-25.md 참고).
    ("20171114002176", "00353610", 2017, "Q3", "separate", 2,
     "자본>자본 합계", -20975944, "true positive (same-basis IS anchor, missed in first pass)"),
    ("20230814000814", "00167031", 2023, "H1", "separate", 5,
     "자본>자본조정", -2952454850, "true positive: treasury-stock balance row must flip negative"),
    ("20210517000597", "00223513", 2021, "Q1", "consolidated", 11,
     "자본>자본 합계", -1322436570, "true positive: dividend outer total must flip negative"),
    ("20151120000371", "00136776", 2015, "Q3", "consolidated", 9,
     "자본>지배기업의 소유주에게 귀속되는 자본>지배기업의 소유주에게 귀속되는 자본 합계",
     -109367799, "true positive: nested subtotal must flip negative"),
    ("20170515004679", "00989664", 2017, "Q1", "separate", 11,
     "자본>이익잉여금", 2690748354, "no dual evidence: 2-column circular identity must stay POSITIVE"),
]


def main() -> int:
    with get_session() as s:
        paths = {}
        for rcept, *_ in TARGETS:
            row = s.execute(text(
                "SELECT file_path FROM download_tasks WHERE rcept_no=:r AND file_type='xml' LIMIT 1"),
                {"r": rcept}).fetchone()
            paths[rcept] = row[0]

    n_ok = 0
    for rcept, corp, fy, period, basis, row_order, col_label, expected, note in TARGETS:
        lines = list(extract_report_lines(
            paths[rcept], rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period, include_notes=True))
        matches = [l for l in lines if getattr(l, "statement", None) == "SCE"
                   and l.basis == basis and l.row_order == row_order and l.col_label == col_label]
        if not matches:
            print(f"[MISS] {rcept} {basis} row={row_order} col={col_label!r} — no matching line found")
            continue
        actual = matches[0].value_won
        status = "OK" if actual == expected else "MISMATCH"
        if status == "OK":
            n_ok += 1
        print(f"[{status}] {rcept} {basis} row={row_order} col={col_label!r} "
              f"expected={expected} actual={actual}  -- {note}")

    print(f"\n{n_ok}/{len(TARGETS)} cases matched expectation")
    return 0 if n_ok == len(TARGETS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
