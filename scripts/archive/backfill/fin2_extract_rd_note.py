"""R&D 갭 복원 — 사업보고서 [연구개발비용] 표에서 rd_expense 적재(연결, FY).

배경/전략: fin2/extract/rd_note.py 참조. R&D 를 face IS XBRL 표준개념으로 태깅한 기업은
소수(~327사)뿐이라 대다수 rd_expense=NULL. 사업보고서 본문 [연구개발비용] 표(DART 표준양식,
보통 백만원)에서 당기 R&D 총액을 추출해 note.rd_expense fact 로 적재한다. 단위가드
(rd/연결매출 ∈ [0.01%,60%])로 가비지 차단. 샘플 복원율 ~80%.

대상: std_v2 consolidated, fiscal_period='FY', rd_expense IS NULL, 연결 IS source + 파일 보유,
      fiscal_year >= year_min. 중복방지: is.rd_expense 우선(rule_rd_fallback 가 NULL 일 때만 채움).
단계: 1) note.rd_expense fact_v2 upsert  2) 영향기업 standardize2 재실행(reconcile 불변).
중단·재개 안전(upsert idempotent). 실행:
  python scripts/fin2_extract_rd_note.py [--year-min 2024] [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.rd_note import extract_rd_facts
from fin2.extract.xbrl import store_facts
from fin2.standardize.build import standardize_corp

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS rc, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis='consolidated' AND ss.statement='IS'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type='consolidated' AND s.version=1 AND s.fiscal_period='FY'
      AND s.rd_expense IS NULL AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
    ORDER BY s.corp_code, s.fiscal_year
"""


def _revenue(session, rcept: str) -> int | None:
    return session.execute(text("""
        SELECT MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis='consolidated'
    """), {"r": rcept}).scalar()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year-min", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        targets = session.execute(text(_TARGET_SQL), {"ymin": args.year_min}).fetchall()
    if args.limit:
        targets = targets[: args.limit]
    logger.info(f"[rd-note] rd_expense-NULL 대상 {len(targets):,}건 (fy>={args.year_min})")

    affected: dict[str, None] = {}
    stored = ok = skip_none = skip_norev = 0
    samples = []
    with get_session() as session:
        for i, t in enumerate(targets, 1):
            if not t.file_path or not Path(t.file_path).exists():
                continue
            rev = _revenue(session, t.rc)
            if not rev:
                skip_norev += 1
                continue
            facts = extract_rd_facts(
                t.file_path, rcept_no=t.rc, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                revenue_ref=rev)
            if not facts:
                skip_none += 1
                continue
            ok += 1
            affected[t.corp_code] = None
            if len(samples) < 12:
                rd = facts[0].amount_won
                samples.append((t.corp_code, t.fiscal_year, f"{rd/1e8:,.0f}억",
                                f"{abs(rd)/rev*100:.1f}%"))
            if not args.dry_run:
                stored += store_facts(session, facts)
            if i % 500 == 0:
                if not args.dry_run:
                    session.commit()
                logger.info(f"[rd-note] {i:,}/{len(targets):,} 복원 {ok} "
                            f"(없음 {skip_none} 무매출 {skip_norev})")
        if not args.dry_run:
            session.commit()

    logger.info(f"[rd-note] 검사 {len(targets):,} → 복원 {ok} / 미복원 {skip_none} / 무매출 {skip_norev}")
    logger.info("샘플 (corp,fy,rd,rd/rev):")
    for s in samples:
        logger.info(f"   {s}")

    if args.dry_run:
        logger.info(f"[rd-note] --dry-run — 쓰기 없음 (복원예정 {ok:,}, 영향기업 {len(affected):,})")
        return

    logger.success(f"[rd-note] E 완료 — note fact {stored:,} upsert, 영향기업 {len(affected):,}")

    corps = list(affected)
    n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[rd-note] S 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[rd-note] S {i:,}/{len(corps):,} (std_v2 {n_std:,})")
    logger.success(f"[rd-note] 완료 — 영향기업 {len(corps):,}, std_v2 {n_std:,} 재계산, 실패 {n_fail}")


if __name__ == "__main__":
    main()
