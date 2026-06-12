"""비교컬럼 폴백 전수 적용 — 자기연도 보고서가 없는 (corp,fy,period,basis) 키를
나중 보고서의 비교컬럼(전기/전전기)에서 합성한다(fin2/standardize/build.py 참조).

대상: parity removed 의 COMPARATIVE_ONLY/OWNREPORT 군(~45K 키). reconcile 가 고른
좋은 보고서의 비교컬럼만 사용 → ×1000·period 불일치 회피. 자기보고서 행 불가침,
파생행은 applied_rules='comparative_fallback' + DQ≥2.

기업 단위 커밋·중단/재개 안전(idempotent). 실행:
  python scripts/fin2_comparative_fallback.py [--limit N] [--corps S:E]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.standardize.build import standardize_comparative_corp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--corps", type=str, default=None, help="S:E 인덱스 범위")
    args = ap.parse_args()

    with get_session() as session:
        corps = [r[0] for r in session.execute(text(
            "SELECT DISTINCT corp_code FROM statement_source ORDER BY corp_code"
        )).fetchall()]
    if args.corps:
        s, e = args.corps.split(":")
        corps = corps[int(s):int(e)]
    if args.limit:
        corps = corps[: args.limit]
    logger.info(f"[comparative] 대상 기업 {len(corps):,}개")

    total = n_fail = affected = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                w = standardize_comparative_corp(session, corp)
                session.commit()
            total += w
            if w:
                affected += 1
        except Exception as e:
            n_fail += 1
            logger.warning(f"[comparative] 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[comparative] {i:,}/{len(corps):,} — 누적 std_v2 {total:,} (영향기업 {affected:,})")

    logger.success(f"[comparative] 완료 — 영향기업 {affected:,}, std_v2 {total:,}레코드 합성, 실패 {n_fail}")


if __name__ == "__main__":
    main()
