"""미매핑 fact_v2 행을 현행 concept_map 으로 재매핑(backfill) + 영향기업 재표준화.

용도: concept_map.py 에 새 ACODE 를 추가한 뒤, **이미 추출돼 canonical_account 가 NULL**
인 기존 fact_v2 행에 소급 적용한다(보고서 재파싱 불필요). 추출시 미등록이라 NULL 인 행만
대상이라 기존 매핑은 건드리지 않는다(안전).

★ 동시성: 재표준화(standardize_corp)는 std_financials_v2 writer 다. D&A 복원 등 다른
재표준화 작업과 **동시 실행 금지**(같은 corp upsert 경쟁/교착). 단독으로 돌릴 것.

실행:
  python scripts/fin2_remap_canonical_gaps.py --dry-run            # 영향만 출력
  python scripts/fin2_remap_canonical_gaps.py                      # backfill + 재표준화
  python scripts/fin2_remap_canonical_gaps.py --no-restandardize   # backfill 만(재표준화 별도)
  python scripts/fin2_remap_canonical_gaps.py --prefix is.         # 특정 prefix 만
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.taxonomy.concept_map import map_acode
from fin2.standardize.build import standardize_corp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-restandardize", action="store_true")
    ap.add_argument("--prefix", default=None, help="이 prefix 의 canonical 만 (예: is. / bs.)")
    args = ap.parse_args()

    with get_session() as session:
        # canonical_account NULL 인 distinct acode → 현행 concept_map 으로 매핑 시도
        rows = session.execute(text("""
            SELECT acode, count(*) AS n, count(DISTINCT corp_code) AS corps
            FROM fact_v2 WHERE canonical_account IS NULL AND acode IS NOT NULL
            GROUP BY acode
        """)).fetchall()

    plan = []  # (acode, canon, n, corps)
    for acode, n, corps in rows:
        canon = map_acode(acode)
        if not canon:
            continue
        if args.prefix and not canon.startswith(args.prefix):
            continue
        plan.append((acode, canon, n, corps))

    if not plan:
        logger.info("[remap] 재매핑 대상 없음(이미 최신).")
        return

    plan.sort(key=lambda t: -t[3])
    total_rows = sum(p[2] for p in plan)
    total_corps = len({})  # placeholder, 실제 corp 집합은 backfill 시 수집
    logger.info(f"[remap] 재매핑 후보 {len(plan)} acode · {total_rows:,} 행")
    for acode, canon, n, corps in plan:
        logger.info(f"   {canon:20s} ← {acode[:50]:50s} 행={n:6d} 기업={corps}")

    if args.dry_run:
        logger.info("[remap] --dry-run — 쓰기 없음.")
        return

    # backfill UPDATE (기존 NULL 만 → 안전) + 영향기업 수집
    affected: set[str] = set()
    with get_session() as session:
        for acode, canon, n, corps in plan:
            cc = session.execute(text("""
                UPDATE fact_v2 SET canonical_account = :canon
                WHERE acode = :acode AND canonical_account IS NULL
                RETURNING corp_code
            """), {"canon": canon, "acode": acode}).fetchall()
            affected.update(r[0] for r in cc)
        session.commit()
    logger.success(f"[remap] backfill 완료 — {total_rows:,} 행, 영향기업 {len(affected):,}")

    if args.no_restandardize:
        logger.info("[remap] --no-restandardize — 재표준화 생략(별도 실행 필요).")
        return

    corps = sorted(affected)
    n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[remap] 재표준화 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[remap] 재표준화 {i:,}/{len(corps):,} (std_v2 {n_std:,})")
    logger.success(f"[remap] 완료 — 영향기업 {len(corps):,}, std_v2 {n_std:,} 재계산, 실패 {n_fail}")


if __name__ == "__main__":
    main()
