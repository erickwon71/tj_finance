"""
acontext 반기(HY)·3분기(TQ) 파싱 버그(commit 2d51ea8) 수정 후, 망가진 보고서만
타깃 재처리한다. 전수 fin2-all 은 7천만 fact 전체를 UPDATE → MVCC 죽은튜플로
fact_v2(35G)가 크게 부풀어 디스크 풀 위험. 본 스크립트는 basis=NULL 로 잘못
추출된 Track A 보고서(약 5,464건)만 재추출하고, 영향 기업만 R→S 재실행한다.

단계:
  1) E: basis NULL + xbrl_acode + HY/TQ/FQ/FY 컨텍스트를 가진 보고서를 식별해
     xbrl.extract_facts → store_facts 로 재추출(ON CONFLICT 로 basis 갱신).
  2) R→S: 영향 기업별 reconcile_corp + standardize_corp 재실행.

중단·재개 안전: upsert idempotent. 죽으면 같은 명령 재실행하면 이어짐(이미 고쳐진
보고서는 basis 가 채워져 재식별 대상에서 빠짐).

실행: python scripts/fin2_reextract_basisnull.py [--limit N] [--min-free-gb 2.0]
  --limit N      : 보고서 N건만(시범). 생략 시 전체.
  --min-free-gb  : 디스크 여유가 이 값 미만이면 중단(기본 2.0).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract import xbrl, text as text_extract
from fin2.extract.xbrl import store_facts
from fin2.reconcile import reconcile_corp
from fin2.standardize.build import standardize_corp

_BROKEN_SQL = """
    SELECT DISTINCT dt.rcept_no, dt.file_path,
           f.corp_code, f.fiscal_year, f.fiscal_period
    FROM fact_v2 v
    JOIN download_tasks dt ON dt.rcept_no = v.rcept_no
    JOIN filings f         ON f.rcept_no = v.rcept_no
    WHERE v.basis IS NULL AND v.source_format = 'xbrl_acode'
      AND v.acontext_raw ~ '^(BP|C|P)FY[0-9]{4}[de](HY|TQ|FQ|FY)'
      AND dt.status = 'completed' AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
    ORDER BY f.corp_code, f.fiscal_year, f.fiscal_period
"""


def _free_gb() -> float:
    return shutil.disk_usage("/").free / 1e9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-free-gb", type=float, default=2.0)
    args = ap.parse_args()

    with get_session() as session:
        rows = session.execute(text(_BROKEN_SQL)).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    logger.info(f"[reextract] 망가진 보고서 {len(rows):,}건 재추출 시작 "
                f"(disk free {_free_gb():.1f}G)")

    # ── 1) E: 보고서 재추출 ─────────────────────────────────────────────
    affected_corps: dict[str, None] = {}
    done = facts_upd = 0
    with get_session() as session:
        for r in rows:
            if _free_gb() < args.min_free_gb:
                session.commit()
                logger.error(f"[reextract] 디스크 여유 {_free_gb():.1f}G < "
                             f"{args.min_free_gb}G — 중단. 공간 확보 후 재실행하면 이어짐.")
                sys.exit(2)

            common = dict(rcept_no=r.rcept_no, corp_code=r.corp_code,
                          report_fiscal_year=r.fiscal_year,
                          report_fiscal_period=r.fiscal_period)
            facts = xbrl.extract_facts(r.file_path, **common)
            if not facts:  # 안전: Track A 가 비면 B 폴백(원래 A 였지만 방어)
                facts = text_extract.extract_facts(r.file_path, **common)
            if facts:
                facts_upd += store_facts(session, facts)
            affected_corps[r.corp_code] = None
            done += 1
            if done % 200 == 0:
                session.commit()
                logger.info(f"[reextract] E {done:,}/{len(rows):,} "
                            f"(fact {facts_upd:,} upsert, free {_free_gb():.1f}G)")
        session.commit()
    logger.success(f"[reextract] E 완료 — 보고서 {done:,}, fact {facts_upd:,} upsert, "
                   f"영향기업 {len(affected_corps):,}")

    # ── 2) R→S: 영향 기업 재정합·재표준화 ───────────────────────────────
    corps = list(affected_corps)
    n_ss = n_std = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_ss += reconcile_corp(session, corp)
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:  # 기업 단위 격리
            logger.warning(f"[reextract] R→S 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[reextract] R→S {i:,}/{len(corps):,} "
                        f"(stmt_src {n_ss:,}, std_v2 {n_std:,})")
    logger.success(f"[reextract] 완료 — 기업 {len(corps):,}, "
                   f"statement_source {n_ss:,}, std_v2 {n_std:,}")


if __name__ == "__main__":
    main()
