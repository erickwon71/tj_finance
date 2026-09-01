"""1회성 소급 이관 — fact_v2.note.employee_benefits/note.raw_materials_used → extended_facts_v3.

배경: docs/plans/factv2_sync_scripts_migration_design_2026-09-01.md §4 항목4.
`collector/expense_nature_sync.py`가 2026-09-01부터 이 두 canonical을 extended_facts_v3에
직접 적재하도록 바뀌었지만(Track 1), 그 전에 fact_v2에 이미 쌓인 과거분(1,954+1,437행)은
저절로 옮겨지지 않는다 — DROP 전에 이 1회성 이관을 안 하면 과거분이 그대로 유실된다.

같은 (corp_code, fiscal_year, fiscal_period, statement_type, canonical_account)에
fact_v2 행이 여러 개(재추출/기재정정으로 인한 중복)면 parsed_at 최신 것을 채택한다
(store_facts()의 "재추출 시 최신값 갱신" 정책과 동일 취지).

사용법:
    python scripts/factv2_backfill_extended_facts_v3_expense_nature.py            # 실행
    python scripts/factv2_backfill_extended_facts_v3_expense_nature.py --dry-run  # 건수만 확인
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import text

from collector.db import get_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_CANONICALS = ("note.employee_benefits", "note.raw_materials_used")

_SELECT_SQL = """
    SELECT DISTINCT ON (corp_code, report_fiscal_year, report_fiscal_period, basis, canonical_account)
           corp_code, report_fiscal_year, report_fiscal_period, basis, canonical_account, amount_won
    FROM fact_v2
    WHERE canonical_account = ANY(:canon)
      AND basis IS NOT NULL AND amount_won IS NOT NULL
    ORDER BY corp_code, report_fiscal_year, report_fiscal_period, basis, canonical_account,
             parsed_at DESC
"""

_UPSERT_SQL = """
    INSERT INTO extended_facts_v3
        (corp_code, fiscal_year, fiscal_period, statement_type, canonical_account, amount_won, built_at)
    VALUES (:corp_code, :fiscal_year, :fiscal_period, :statement_type, :canonical_account, :amount_won, now())
    ON CONFLICT (corp_code, fiscal_year, fiscal_period, statement_type, canonical_account)
    DO UPDATE SET amount_won = EXCLUDED.amount_won, built_at = EXCLUDED.built_at
"""


def backfill(dry_run: bool = False) -> dict:
    with get_session() as session:
        rows = session.execute(text(_SELECT_SQL), {"canon": list(_CANONICALS)}).fetchall()

    logger.info(f"[backfill] fact_v2 소스 행 {len(rows):,}건 (중복 제거 후, canonical={_CANONICALS})")
    if dry_run:
        by_canon: dict[str, int] = {}
        for r in rows:
            by_canon[r.canonical_account] = by_canon.get(r.canonical_account, 0) + 1
        for k, v in sorted(by_canon.items()):
            logger.info(f"[backfill]   {k}: {v:,}건")
        return {"rows": len(rows), "dry_run": True}

    params = [
        {
            "corp_code": r.corp_code,
            "fiscal_year": r.report_fiscal_year,
            "fiscal_period": r.report_fiscal_period,
            "statement_type": r.basis,
            "canonical_account": r.canonical_account,
            "amount_won": r.amount_won,
        }
        for r in rows
    ]
    with get_session() as session:
        for p in params:
            session.execute(text(_UPSERT_SQL), p)
        session.commit()
    logger.info(f"[backfill] extended_facts_v3 upsert 완료 — {len(params):,}행")
    return {"rows": len(params), "dry_run": False}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="건수만 출력, DB 쓰기 없음")
    args = ap.parse_args()
    result = backfill(dry_run=args.dry_run)
    logger.info(f"[backfill] 완료: {result}")
