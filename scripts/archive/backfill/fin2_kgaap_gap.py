"""K-GAAP(pre-IFRS) 갭 채우기 — 자기보고서 없는 구년도를 K-GAAP 원본으로 보충.

배경: section_detector 의 대차대조표+TABLE-GROUP 중첩 수정으로 K-GAAP 보고서가
파싱 가능해짐(commit feat(parser): K-GAAP 섹션 탐지). 단 K-GAAP 원본값은 IFRS
재작성 비교컬럼과 상충하므로, **기존 std_v2 행이 없는 키(대개 pre-2007)만** 보충한다
(standardize_kgaap_gap_corp). 대상=pre-2011 FY 보고서가 있으나 std_v2 행이 없는 480기업.

기업 단위(resumable, 진행파일). 각 기업: pre-2011 보고서 재추출 → reconcile_corp →
standardize_kgaap_gap_corp(기존행 불가침). 실행:
  python scripts/fin2_kgaap_gap.py [--limit N]
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
from fin2.standardize.build import standardize_kgaap_gap_corp

_PROGRESS = Path("/tmp/kgaap_gap_done.txt")

_GAP_CORPS_SQL = """
WITH rep AS (
  SELECT DISTINCT f.corp_code, f.fiscal_year
  FROM filings f JOIN download_tasks dt ON dt.rcept_no=f.rcept_no
    AND dt.status='completed' AND dt.file_type='xml'
  WHERE f.fiscal_year<2011 AND f.fiscal_period='FY')
SELECT DISTINCT corp_code FROM rep
WHERE NOT EXISTS (SELECT 1 FROM std_financials_v2 s
                  WHERE s.corp_code=rep.corp_code AND s.fiscal_year=rep.fiscal_year AND s.version=1)
ORDER BY corp_code
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    done = set(_PROGRESS.read_text().split()) if _PROGRESS.exists() else set()
    with get_session() as session:
        corps = [r[0] for r in session.execute(text(_GAP_CORPS_SQL)).fetchall()]
    todo = [c for c in corps if c not in done]
    if args.limit:
        todo = todo[: args.limit]
    logger.info(f"[kgaap-gap] 갭 기업 {len(corps):,} / 잔여 {len(todo):,}")

    n_rows = n_fail = affected = 0
    pf = _PROGRESS.open("a")
    for i, corp in enumerate(todo, 1):
        try:
            with get_session() as session:
                reps = session.execute(text("""
                    SELECT dt.rcept_no, dt.file_path, f.fiscal_year, f.fiscal_period
                    FROM filings f JOIN download_tasks dt ON dt.rcept_no=f.rcept_no
                      AND dt.file_type='xml' AND dt.status='completed'
                    WHERE f.corp_code=:c AND f.fiscal_year<2011 AND dt.file_path IS NOT NULL
                """), {"c": corp}).fetchall()
                for r in reps:
                    if not r.file_path or not Path(r.file_path).exists():
                        continue
                    common = dict(rcept_no=r.rcept_no, corp_code=corp,
                                  report_fiscal_year=r.fiscal_year, report_fiscal_period=r.fiscal_period)
                    facts = xbrl.extract_facts(r.file_path, **common)
                    if not facts:
                        facts = text_extract.extract_facts(r.file_path, **common)
                    store_facts(session, facts)
                reconcile_corp(session, corp)
                w = standardize_kgaap_gap_corp(session, corp)
                session.commit()
            n_rows += w
            if w:
                affected += 1
            pf.write(corp + "\n"); pf.flush()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[kgaap-gap] 실패 corp={corp}: {e}")
        if i % 50 == 0:
            logger.info(f"[kgaap-gap] {i:,}/{len(todo):,} — std_v2 {n_rows:,} (영향 {affected:,})")
    pf.close()
    logger.success(f"[kgaap-gap] 완료 — 영향기업 {affected:,}, std_v2 {n_rows:,}레코드, 실패 {n_fail}")


if __name__ == "__main__":
    main()
