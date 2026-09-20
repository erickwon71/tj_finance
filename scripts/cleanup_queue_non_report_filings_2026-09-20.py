#!/usr/bin/env python
"""계층2 캠페인 큐에서 '제출기한연장신고서' 를 걷어낸다 (2026-09-20).

근거: `docs/qa/layer2_blocked_filings_investigation_2026-09-20.md` §①

`사업보고서제출기한연장신고서`(ACODE 11061) 류는 `report_nm` 이 '사업보고서…' 로
시작해 `report_type='annual'` 로 분류되지만 **재무제표가 있을 수 없는 서류**다
(본문 6KB 남짓, `<TABLE>` 0개 — 실측 케이티앤지 `20200320001044`). 큐에 남겨두면
전부 "추출 0행"으로 blocked 되어 검토자 시간만 버린다.

`scripts/layer2_review.py::_FILINGS_SQL` 에 같은 조건을 넣어 **앞으로 init 은
이걸 담지 않는다.** 이 스크립트는 **이미 들어가 있는 행**을 정리하는 1회용이다.

## 안전장치
- 기본이 **dry-run** 이다. 실제로 쓰려면 `--apply` 를 붙인다.
- `status='pending'`/`'blocked'` 인 행만 건드린다 — 사람이 이미 `pass`/`fail` 판단을
  남긴 행은 절대 손대지 않는다(ReconCandidate 관례).
- 실데이터(`report_lines`)가 한 줄이라도 있는 rcept 는 **건너뛴다.** 이름만 보고
  지우지 않는다는 뜻 — 혹시라도 분류가 틀린 건이 있으면 사람이 보게 남긴다.

## 사용법
    python scripts/cleanup_queue_non_report_filings_2026-09-20.py
    python scripts/cleanup_queue_non_report_filings_2026-09-20.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from scripts.layer2_review import _NON_REPORT_NM

_TARGETS = text(
    """
    SELECT q.rcept_no, q.corp_name, q.fiscal_year, q.fiscal_period, q.status,
           q.report_nm,
           (SELECT count(*) FROM report_lines rl WHERE rl.rcept_no = q.rcept_no) AS n_lines
    FROM layer2_review_queue q
    WHERE q.report_nm LIKE :p
      AND q.status IN ('pending', 'blocked')
    ORDER BY q.fiscal_year DESC, q.rcept_no
    """
)

_SKIP = text(
    """
    UPDATE layer2_review_queue
       SET status = 'skipped', note = :note, reviewed_at = now()
     WHERE rcept_no = :r
    """
)

_NOTE = ("정기보고서가 아님(제출기한연장신고서 — 재무제표 없음). "
         "docs/qa/layer2_blocked_filings_investigation_2026-09-20.md §①")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="실제로 status='skipped' 로 바꾼다(기본은 dry-run)")
    args = ap.parse_args()

    with get_session() as session:
        rows = session.execute(_TARGETS, {"p": _NON_REPORT_NM}).fetchall()
        # 실데이터가 있으면 이름만 보고 지우지 않는다 — 사람이 보게 남긴다.
        skippable = [r for r in rows if not r.n_lines]
        has_data = [r for r in rows if r.n_lines]

        logger.info(f"대상 {len(rows):,}건 (pending/blocked 만) — "
                    f"정리 {len(skippable):,}건, 실데이터 있어 보류 {len(has_data):,}건")
        for r in has_data:
            logger.warning(f"  [보류] {r.rcept_no} {r.corp_name} "
                           f"FY{r.fiscal_year}{r.fiscal_period} lines={r.n_lines} "
                           f"{r.report_nm!r}")

        by_status: dict[str, int] = {}
        for r in skippable:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        logger.info(f"  상태별: {by_status}")

        if not args.apply:
            logger.info("dry-run — 쓰지 않았다. 실행하려면 --apply")
            for r in skippable[:10]:
                logger.info(f"  예시: {r.rcept_no} {r.corp_name} {r.report_nm!r}")
            return

        for r in skippable:
            session.execute(_SKIP, {"r": r.rcept_no, "note": _NOTE})
        session.commit()
        logger.success(f"[cleanup] {len(skippable):,}건 → status='skipped'")


if __name__ == "__main__":
    main()
