"""기재정정 우선 reconcile 수정(commit 4b5a0a8)을 전수 적용.

select_source 에 is_amendment 우선이 추가돼, 기재정정본이 원본을 대체해야 하는
(corp,fy,fp,basis,stmt) 키들의 source 선택이 바뀐다(jiitech ×1000 류). 이 스크립트는:
  1) 새 규칙으로 source 가 바뀌는 '플립' 기업을 fact_v2 에서 산출.
  2) 각 기업 reconcile_corp + standardize_corp 재실행(기업 단위 커밋·재개 안전).
  3) CF source 플립으로 연결 D&A(depreciation)가 NULL 로 떨어진 기업은 cf_da.recover_cf_da
     로 재복원 + 재표준화(2024+ 갭 복원 보존).

읽기전용 산출 후 쓰기. 중단·재개 안전(idempotent). 실행:
  python scripts/fin2_apply_amendment_fix.py [--dry-run] [--limit N]
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
from fin2.extract.cf_da import recover_cf_da
from fin2.extract.xbrl import store_facts

# 새 규칙(anchor>is_amendment>완전성>filed_at>rcept) 으로 선택이 바뀌는 키의 기업 목록.
_FLIP_CORPS_SQL = """
WITH cand AS (
  SELECT f.corp_code, f.report_fiscal_year fy, f.report_fiscal_period fp, f.basis,
         CASE WHEN f.canonical_account LIKE 'bs.%' THEN 'BS'
              WHEN f.canonical_account LIKE 'is.%' THEN 'IS'
              WHEN f.canonical_account LIKE 'cf.%' THEN 'CF' END AS stmt,
         f.rcept_no,
         bool_or(f.canonical_account IN ('bs.total_assets','is.revenue','cf.operating')) AS has_anchor,
         bool_or(COALESCE(fl.is_amendment,false)) AS is_amend,
         count(DISTINCT f.canonical_account) AS lines,
         max(fl.filed_at) AS filed_at
  FROM fact_v2 f JOIN filings fl ON fl.rcept_no=f.rcept_no
  WHERE f.col_index=0 AND NOT f.is_dimensional AND f.canonical_account IS NOT NULL
    AND f.basis IN ('consolidated','separate')
  GROUP BY 1,2,3,4,5,6
),
cand2 AS (  -- 적시 기재정정만 우선 신호(select_source._AMEND_WINDOW_DAYS=400 와 일치)
  SELECT c.*,
         c.is_amend AND c.filed_at <= (min(c.filed_at) OVER (
           PARTITION BY corp_code,fy,fp,basis,stmt)) + 400 AS timely_amend
  FROM cand c WHERE stmt IS NOT NULL
),
ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY corp_code,fy,fp,basis,stmt
    ORDER BY has_anchor DESC, timely_amend DESC, lines DESC, filed_at DESC NULLS LAST, rcept_no DESC
  ) rn FROM cand2
)
SELECT DISTINCT r.corp_code
FROM ranked r
JOIN statement_source ss
  ON ss.corp_code=r.corp_code AND ss.fiscal_year=r.fy AND ss.fiscal_period=r.fp
 AND ss.basis=r.basis AND ss.statement=r.stmt
WHERE r.rn=1 AND ss.source_rcept_no <> r.rcept_no
ORDER BY r.corp_code
"""

# 재표준화 후 연결 depreciation 이 NULL 인 (corp,fy,fp) — D&A 재복원 대상(연결 CF source 보유).
_DA_NULL_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis='consolidated' AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.corp_code = ANY(:corps) AND s.statement_type='consolidated' AND s.version=1
      AND s.depreciation IS NULL AND s.fiscal_year >= 2024 AND dt.file_path IS NOT NULL
"""


def _revenue_by_basis(session, rcept):
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with get_session() as session:
        corps = [r[0] for r in session.execute(text(_FLIP_CORPS_SQL)).fetchall()]
    if args.limit:
        corps = corps[: args.limit]
    logger.info(f"[amend-fix] source 플립 기업 {len(corps):,}개 — reconcile+standardize 재실행")

    if args.dry_run:
        logger.info(f"[amend-fix] --dry-run — 대상 기업 {len(corps):,} (쓰기 없음). 샘플: {corps[:10]}")
        return

    # 1) R+S 재실행
    n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                reconcile_corp(session, corp)
                standardize_corp(session, corp)
                session.commit()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[amend-fix] R+S 실패 corp={corp}: {e}")
        if i % 100 == 0:
            logger.info(f"[amend-fix] R+S {i:,}/{len(corps):,}")
    logger.success(f"[amend-fix] R+S 완료 — {len(corps):,}개, 실패 {n_fail}")

    # 2) CF 플립으로 떨어진 연결 D&A 재복원(idempotent, depreciation NULL 만)
    with get_session() as session:
        targets = session.execute(text(_DA_NULL_SQL), {"corps": corps}).fetchall()
    logger.info(f"[amend-fix] 연결 D&A-NULL 재복원 대상 {len(targets):,}건")
    restored = 0
    affected: dict[str, None] = {}
    with get_session() as session:
        for t in targets:
            if not t.file_path or not Path(t.file_path).exists():
                continue
            rev = _revenue_by_basis(session, t.cf_rcept)
            facts, src = recover_cf_da(
                t.file_path, rcept_no=t.cf_rcept, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                basis="consolidated", revenue_by_basis=rev,
            )
            if facts:
                store_facts(session, facts)
                restored += 1
                affected[t.corp_code] = None
        session.commit()
    # 재복원분 재표준화
    for corp in affected:
        with get_session() as session:
            standardize_corp(session, corp)
            session.commit()
    logger.success(f"[amend-fix] D&A 재복원 {restored:,}건 / 재표준화 기업 {len(affected):,}. 완료.")


if __name__ == "__main__":
    main()
