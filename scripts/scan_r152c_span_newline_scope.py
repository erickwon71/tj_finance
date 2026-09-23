#!/usr/bin/env python
"""R152-c scope scan (2026-09-23, camp_run 이슈#41) — how many filings have a
compacted 대손준비금/비상위험준비금 supplementary row whose 본항목 amount is still
missing after the SPAN-boundary-newline fix (`_first_of_compacted_supplementary_cell`)?

## Population

Filings that ALREADY use this label pattern somewhere in `report_lines` (any
statement, matched via `_SUPPLEMENTARY_RESERVE_RE`) — narrower and cheaper than
a full-corpus XML scan, and correct because R152 itself only fires on that
label. A filing whose current DB output has the compacted-label row present is
NOT missing anything (R152/R152-b already recovered it); this scan only flags
filings where the row is genuinely absent from a fresh re-extraction with the
CURRENT code, i.e. the SPAN-newline defect this fix targets.

## Why not fix-then-diff against DB

DB may already be stale from before ANY of R152/R152-b/R152-c shipped. This
scan re-extracts with today's code and reports what's recoverable now,
independent of what happened to land in the DB historically.

Usage:
    python scripts/scan_r152c_span_newline_scope.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

_RESERVE_RE = re.compile(r"대손준비금|비상위험준비금")

_LINK = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"


def main() -> int:
    with get_session() as s:
        rcepts = s.execute(text("""
            SELECT DISTINCT rcept_no FROM report_lines
            WHERE label_raw ~ '대손준비금|비상위험준비금'""")).scalars().all()
        print(f"모집단(보충표기 라벨 보유 필링) {len(rcepts)}건")

        meta = {r["rcept_no"]: dict(r) for r in s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, f.corp_code, f.corp_name,
                   f.fiscal_year, f.fiscal_period
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            WHERE dt.rcept_no = ANY(:r) AND dt.file_type='xml'"""),
            {"r": rcepts}).mappings()}

        affected = []
        errors = []
        for i, rcept in enumerate(rcepts, 1):
            m = meta.get(rcept)
            if not m:
                continue
            path = Path(_SD + m["file_path"][len(_LINK):]
                        if m["file_path"].startswith(_LINK) else m["file_path"])
            try:
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=m["corp_code"],
                    report_fiscal_year=m["fiscal_year"],
                    report_fiscal_period=m["fiscal_period"])
            except Exception as exc:                        # noqa: BLE001
                errors.append((rcept, str(exc)[:80]))
                continue
            # ★col_index=0 로만 좁힌다 — DB 는 당기(col_index=0)만 적재한다
            #   (`_is_loadable`, R6/2026-07-30). 초판은 이 필터가 없어 전기/전전기
            #   컬럼까지 "DB 에 없는 행"으로 잡혀 1,820건 중 84% 가 오탐으로
            #   "영향"에 걸렸다(비교 대상 자체가 잘못됨) — DB 대조 전에 반드시
            #   적재 스코프와 같은 조건으로 좁혀야 한다.
            fresh_rcept_labels = {
                (l.statement, l.basis)
                for l in lines
                if (l.col_index or 0) == 0 and l.label_raw
                and _RESERVE_RE.search(l.label_raw)}
            db_labels = {(r["statement"], r["basis"])
                        for r in s.execute(text("""
                            SELECT statement, basis FROM report_lines
                            WHERE rcept_no=:r AND col_index=0
                              AND label_raw ~ '대손준비금|비상위험준비금'"""),
                            {"r": rcept}).mappings()}
            missing_from_db = fresh_rcept_labels - db_labels
            if missing_from_db:
                affected.append((rcept, m["corp_name"], m["fiscal_year"],
                                 m["fiscal_period"], sorted(missing_from_db)))
            if i % 50 == 0:
                print(f"  ... {i}/{len(rcepts)}  affected={len(affected)}",
                      flush=True)

        print(f"\n측정 {len(rcepts)}건 · 오류 {len(errors)}건 · "
              f"영향(현재 DB 에 없는데 재추출하면 생기는 행) {len(affected)}건")
        for rcept, name, fy, fp, missing in affected:
            print(f"  {rcept}  {name:16}  {fy}{fp}  {missing}")
        for rcept, err in errors[:10]:
            print(f"  ERROR {rcept}: {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
