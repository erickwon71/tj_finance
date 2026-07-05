"""
신규/증분 보고서 D&A note 복원 — collect_new 파이프라인 영속화 (B5).

배경: DART 2024+ Track A 전환으로 연결 현금흐름표 감가상각이 개별 XBRL ACODE 로
태깅되지 않아(집계라인만) fin2/extract/xbrl.py 가 놓친다 → EBITDA/da_total 절벽.
일회성 백필(scripts/fin2_extract_cf_da_consolidated.py)로 과거분은 복원했으나, 추출이
표준 파이프라인에 없어 **신규 보고서는 D&A 를 못 받고 재퇴행**(2026 신규 EBITDA ~11%).

이 모듈은 그 백필과 동일 로직을 **corp 한정**으로 수행: 연결 FY depreciation NULL +
연결 CF source 보유(fy>=year_min) 보고서에 note.* D&A fact 를 하이브리드 복원
(주석 우선·본문 폴백, 단위가드 da/매출∈[0.3%,60%]) → fact_v2 upsert → 영향기업 재표준화.
collect_new 가 매일 신규표준화 corp 에 호출 → EBITDA 재퇴행 방지(상한 자체는 데이터 부재).

주의: depreciation IS NULL(본문 D&A 없는 보고서)만 손대 중복합산을 막는다. upsert idempotent.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.cf_da import recover_cf_da
from fin2.extract.xbrl import store_facts
from fin2.standardize.build import standardize_corp
from fin2.standardize.calendar import calendarize_corp
from fin2.standardize.quarterly import derive_quarters_corp

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis=:basis AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type=:basis AND s.version=1 AND s.depreciation IS NULL
      AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
      {corp_clause}
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def _revenue_by_basis(session, rcept: str) -> dict[str, int]:
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def sync_cf_da(corps=None, year_min: int = 2024, basis: str = "consolidated") -> dict:
    """corp 한정 D&A note 복원 + 재표준화. corps=None 이면 전체(백필용).

    반환: {targets, corps, facts, std_recalc, fail}."""
    corp_clause = "AND s.corp_code = ANY(:corps)" if corps else ""
    sql = _TARGET_SQL.format(corp_clause=corp_clause)
    params: dict = {"basis": basis, "ymin": year_min}
    if corps:
        params["corps"] = list(corps)

    with get_session() as session:
        targets = session.execute(text(sql), params).fetchall()

    affected: dict[str, None] = {}
    stored = 0
    with get_session() as session:
        for t in targets:
            if not t.file_path or not Path(t.file_path).exists():
                continue
            rev = _revenue_by_basis(session, t.cf_rcept)
            if not rev.get(basis):
                continue
            facts, _source = recover_cf_da(
                t.file_path, rcept_no=t.cf_rcept, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                basis=basis, revenue_by_basis=rev,
            )
            if not facts:
                continue
            affected[t.corp_code] = None
            stored += store_facts(session, facts)
        session.commit()

    # R 불변(note 는 source 선택 무관) → S→Q→C 재전파(누적 std_v2 + 이산분기 + 달력뷰까지
    # D&A/EBITDA 반영; S 단독이면 분기/달력 뷰가 stale — 메모리 data-coverage-gaps 교훈).
    n_std = n_fail = 0
    for corp in affected:
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                derive_quarters_corp(session, corp)
                calendarize_corp(session, corp)
                session.commit()
        except Exception:  # noqa: BLE001 — 개별 corp 실패는 격리(비치명)
            n_fail += 1
    return {"targets": len(targets), "corps": len(affected), "facts": stored,
            "std_recalc": n_std, "fail": n_fail}
