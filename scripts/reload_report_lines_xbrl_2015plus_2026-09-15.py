#!/usr/bin/env python
"""2015+ XBRL-소스 필링 report_lines 전수 재적재 — 현재 파서(R129/R130 포함) 적용.

배경: `scripts/reload_report_lines_2015plus_2026-09-12.py`는 `file_type='xml'`(본문
XML) 필링만 대상으로 한다 — `extract_report_lines()`만 부르고 `extract_report_lines_
xbrl()`은 아예 호출하지 않는다(코드에 직접 확인). `scripts/backfill_xbrl_instance_
lines_2026-08-18.py`는 반대로 "아직 한 번도 XBRL로 안 실린" rcept만 골라 append하는
1회성 갭채움용이라(`NOT EXISTS (report_lines WHERE unit_source='xbrl')`) 이미
`unit_source='xbrl'` 행이 있는 필링은 최신 코드가 있어도 건드리지 않는다 — R129/R130
(2026-09-15)을 기존 XBRL 소스 필링 전체에 적용하려면 이 갭을 메울 별도 스크립트가
필요하다.

## 대상
`report_lines.unit_source='xbrl'` 행이 이미 존재하는 rcept 전체(2015+) — 즉 지금
"XBRL 경로로 적재된 필링"으로 이미 알려진 것들을 현재 파서로 재추출한다.
`store_report_lines()`가 rcept 단위 delete-then-insert라 멱등 — 중간에 죽어도
다시 돌리면 안전하다.

## 사용법
    python scripts/reload_report_lines_xbrl_2015plus_2026-09-15.py --dry-run
    python scripts/reload_report_lines_xbrl_2015plus_2026-09-15.py
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.models import ReportLineLoadProgress
from fin2.extract.report_lines import store_report_lines, store_report_tables
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl

_TARGETS_SQL = text(
    """
    WITH universe AS (
        SELECT c.corp_code
        FROM corporations c
        WHERE c.is_active
          AND c.stock_code IS NOT NULL
          AND c.stock_code NOT LIKE '9%'
          AND c.coverage_class = 'periodic'
    )
    SELECT DISTINCT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year,
           f.fiscal_period, f.period_end_date
    FROM report_lines r
    JOIN download_tasks dt ON dt.rcept_no = r.rcept_no
    JOIN filings f ON f.rcept_no = r.rcept_no
    JOIN universe u ON u.corp_code = f.corp_code
    LEFT JOIN layer2_review_queue lrq ON lrq.rcept_no = f.rcept_no
    WHERE r.unit_source = 'xbrl'
      AND f.fiscal_year >= :fy_min
      AND dt.status = 'completed'
      AND dt.file_type = 'xbrl_zip'
      AND dt.file_path IS NOT NULL
      AND (lrq.status IS NULL OR lrq.status <> 'pass')
    ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
    """
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fiscal-year-min", type=int, default=2015)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as s:
        rows = [dict(r) for r in s.execute(
            _TARGETS_SQL, {"fy_min": args.fiscal_year_min}).mappings()]
    if args.limit:
        rows = rows[: args.limit]
    logger.info(f"대상 {len(rows)}건")
    if args.dry_run:
        return

    n_done = n_skip_manual = n_error = n_empty = 0
    t0 = time.time()
    with get_session() as s:
        prev_corp = None
        for i, r in enumerate(rows, start=1):
            if prev_corp is not None and r["corp_code"] != prev_corp:
                s.commit()
            prev_corp = r["corp_code"]

            path = Path(r["file_path"])
            if not path.exists():
                n_error += 1
                logger.warning(f"파일 없음 {r['rcept_no']} ({path})")
                continue
            try:
                lines = extract_report_lines_xbrl(
                    path, rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    report_fiscal_year=r["fiscal_year"],
                    report_fiscal_period=r["fiscal_period"],
                    period_end_date=r["period_end_date"])
            except Exception as exc:  # noqa: BLE001
                n_error += 1
                logger.error(f"추출 실패 {r['rcept_no']}: {type(exc).__name__}: {exc}")
                continue

            if not lines:
                n_empty += 1
                s.merge(ReportLineLoadProgress(
                    rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    fiscal_year=r["fiscal_year"], status="done", n_lines=0,
                    message="reload_xbrl_2015plus: 0행", processed_at=datetime.utcnow()))
                continue

            try:
                nl = store_report_lines(s, r["rcept_no"], lines)
                store_report_tables(s, r["rcept_no"], lines)
            except ValueError as exc:
                s.rollback()
                n_skip_manual += 1
                logger.warning(f"manual-protected 스킵 {r['rcept_no']}: {exc}")
                continue

            n_done += 1
            if i % 200 == 0:
                elapsed = time.time() - t0
                logger.info(f"{i}/{len(rows)} done={n_done} empty={n_empty} "
                            f"manual_skip={n_skip_manual} error={n_error} "
                            f"({elapsed:.0f}s)")
        s.commit()

    logger.info(f"완료: done={n_done} empty={n_empty} manual_skip={n_skip_manual} "
                f"error={n_error} / 총 {len(rows)}건, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
