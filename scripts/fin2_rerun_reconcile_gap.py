"""
RECON_DROP_OWNPERIOD 복구: reextract(fin2_reextract_basisnull.py)의 E 단계가
basis 를 고쳤지만 R→S(reconcile→standardize)를 못 받은 기업을 타깃 재실행한다.

배경: reextract 는 affected_corps(브로큰 보고서를 가진 ~1,020사)에만 R→S 를 돌렸다.
그러나 E 가 basis 를 채운 own-period(H1/Q3 등) fact 가 reconcile 필터를 전부 통과함에도
statement_source 가 없는 기업이 ~1,472사 존재(std_v2 가 06-06 stale 상태로 잔존).
이들에 reconcile_corp + standardize_corp 만 재실행하면 H1/Q3 가 복구된다(fact_v2 는 이미 완전).

갭 정의(GAP_CORPS_SQL):
  fact_v2 에서 col_index=0 · 비차원 · canonical(bs/is/cf) · basis∈(con,sep) 인
  (corp, report_fy, report_period, basis, statement) 셀이 존재하는데,
  statement_source 에 같은 셀이 **없는** 기업.

단계: 갭 기업마다 reconcile_corp → standardize_corp 재실행(기업 단위 커밋·예외 격리).
중단·재개 안전: idempotent(upsert). 고쳐진 기업은 다음 실행 시 갭에서 빠짐.

실행: python scripts/fin2_rerun_reconcile_gap.py [--limit N] [--dry-run]
  --limit N   : 갭 기업 N개만(시범).
  --dry-run   : 갭 기업 목록·수만 출력하고 종료(쓰기 없음).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.reconcile import reconcile_corp
from fin2.standardize.build import standardize_corp

# reconcile 이 후보로 쓰는 셀(col_index=0 · 비차원 · canonical bs/is/cf · basis∈con/sep)이
# 존재하지만 statement_source 에 같은 셀이 없는 기업을 추린다.
GAP_CORPS_SQL = """
WITH passing AS (
    SELECT DISTINCT
        v.corp_code,
        v.report_fiscal_year   AS fy,
        v.report_fiscal_period AS fp,
        v.basis,
        split_part(v.canonical_account, '.', 1) AS stmt
    FROM fact_v2 v
    WHERE v.col_index = 0
      AND NOT v.is_dimensional
      AND v.canonical_account IS NOT NULL
      AND v.basis IN ('consolidated', 'separate')
      AND split_part(v.canonical_account, '.', 1) IN ('bs', 'is', 'cf')
),
ss AS (
    SELECT corp_code,
           fiscal_year      AS fy,
           fiscal_period    AS fp,
           basis,
           lower(statement) AS stmt
    FROM statement_source
)
SELECT DISTINCT p.corp_code
FROM passing p
LEFT JOIN ss
       ON ss.corp_code = p.corp_code
      AND ss.fy        = p.fy
      AND ss.fp        = p.fp
      AND ss.basis     = p.basis
      AND ss.stmt      = p.stmt
WHERE ss.corp_code IS NULL
ORDER BY p.corp_code
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        corps = [r.corp_code for r in session.execute(text(GAP_CORPS_SQL)).fetchall()]
    if args.limit:
        corps = corps[: args.limit]

    logger.info(f"[rerun-gap] R→S 재실행 대상(갭) 기업 {len(corps):,}사")
    if args.dry_run:
        for c in corps[:50]:
            logger.info(f"  {c}")
        if len(corps) > 50:
            logger.info(f"  ... 외 {len(corps) - 50:,}사")
        logger.info("[rerun-gap] --dry-run — 쓰기 없이 종료")
        return

    n_ss = n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_ss += reconcile_corp(session, corp)
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:  # 기업 단위 격리
            n_fail += 1
            logger.warning(f"[rerun-gap] R→S 실패 corp={corp}: {e}")
        if i % 100 == 0:
            logger.info(f"[rerun-gap] {i:,}/{len(corps):,} "
                        f"(stmt_src {n_ss:,}, std_v2 {n_std:,}, 실패 {n_fail})")

    logger.success(f"[rerun-gap] 완료 — 기업 {len(corps):,}, "
                   f"statement_source {n_ss:,}, std_v2 {n_std:,}, 실패 {n_fail}")


if __name__ == "__main__":
    main()
