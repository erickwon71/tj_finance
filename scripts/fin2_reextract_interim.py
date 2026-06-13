"""Track B 반기/3분기 보고서 전수 재추출 — 누적컬럼 정합 적용(commit: text.py interim).

배경: Track B 가 반기/3분기 IS·CF 의 [3개월|누적] 2단 헤더를 위치순 처리해 3개월을
누적으로 오라벨하고 연도가 밀렸음(text._interim_cumulative_cols 로 수정). 이미 적재된
xml_text interim fact 를 재추출해 교정한다.

기업 단위 처리(resumable, 진행파일). 각 기업:
  1) 해당 기업의 H1/Q3 보고서(xml_text)의 fact 삭제(스트래글러 col2/3 제거; note.* 보존)
  2) 그 보고서들을 재추출(Track A 우선·0행이면 Track B) upsert
  3) reconcile_corp + standardize_corp 재실행
중단 시 같은 명령 재실행하면 진행파일 이후부터 이어짐.

실행: python scripts/fin2_reextract_interim.py [--limit N]
"""
from __future__ import annotations

import argparse
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

_PROGRESS = Path("/tmp/reextract_interim_done.txt")


def _interim_reports(session, corp):
    return session.execute(text("""
        SELECT DISTINCT dt.rcept_no, dt.file_path, f.fiscal_year, f.fiscal_period
        FROM fact_v2 fv
        JOIN download_tasks dt ON dt.rcept_no = fv.rcept_no AND dt.file_type='xml'
        JOIN filings f ON f.rcept_no = fv.rcept_no
        WHERE fv.corp_code = :c AND fv.source_format='xml_text'
          AND fv.report_fiscal_period IN ('H1','Q3') AND dt.file_path IS NOT NULL
    """), {"c": corp}).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    done = set()
    if _PROGRESS.exists():
        done = set(_PROGRESS.read_text().split())

    with get_session() as session:
        corps = [r[0] for r in session.execute(text("""
            SELECT DISTINCT corp_code FROM fact_v2
            WHERE source_format='xml_text' AND report_fiscal_period IN ('H1','Q3')
            ORDER BY corp_code
        """)).fetchall()]
    todo = [c for c in corps if c not in done]
    if args.limit:
        todo = todo[: args.limit]
    logger.info(f"[reextract-interim] 전체 {len(corps):,} / 잔여 {len(todo):,} 기업")

    n_reports = n_fail = 0
    pf = _PROGRESS.open("a")
    for i, corp in enumerate(todo, 1):
        try:
            with get_session() as session:
                reps = _interim_reports(session, corp)
                for r in reps:
                    if not r.file_path or not Path(r.file_path).exists():
                        continue
                    # 스트래글러 제거: 이 보고서의 xml_text fact 삭제 후 재추출
                    session.execute(text(
                        "DELETE FROM fact_v2 WHERE rcept_no=:r AND source_format='xml_text'"
                    ), {"r": r.rcept_no})
                    common = dict(rcept_no=r.rcept_no, corp_code=corp,
                                  report_fiscal_year=r.fiscal_year, report_fiscal_period=r.fiscal_period)
                    facts = xbrl.extract_facts(r.file_path, **common)
                    if not facts:
                        facts = text_extract.extract_facts(r.file_path, **common)
                    store_facts(session, facts)
                    n_reports += 1
                reconcile_corp(session, corp)
                standardize_corp(session, corp)
                session.commit()
            pf.write(corp + "\n"); pf.flush()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[reextract-interim] 실패 corp={corp}: {e}")
        if i % 100 == 0:
            logger.info(f"[reextract-interim] {i:,}/{len(todo):,} (보고서 {n_reports:,}, 실패 {n_fail})")
    pf.close()
    logger.success(f"[reextract-interim] 완료 — 기업 {len(todo):,}, 보고서 {n_reports:,} 재추출, 실패 {n_fail}")


if __name__ == "__main__":
    main()
