"""신규/증분 보고서 '비용의 성격별 분류' D&A 복원 — collect_new 파이프라인 영속화 (Phase 4).

collector/cf_da_sync.py 의 정확한 클론. 차이:
  - 소스 statement='IS'(비용성격 주석은 손익 관련 절 — IS 승자 rcept + file_path 로 파싱/적재).
  - 추출기 = fin2.extract.expense_nature.extract_expense_nature_facts.
  - cf_da_sync 다음에 돌아 **여전히 depreciation IS NULL** 인 잔여만 타겟 → 이중 계상 방지
    (cf_da 가 CF 경로로 채우지 못한 보고서에서만 비용성격 주석으로 D&A 를 보충).

순서 필수(data-coverage-gaps 교훈): 추출→store_facts→standardize_corp→derive_quarters_corp→
calendarize_corp. calendar 단독은 stale.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.expense_nature import extract_expense_nature_facts
from fin2.extract.xbrl import store_facts
from fin2.standardize.build import standardize_corp
from fin2.standardize.calendar import calendarize_corp
from fin2.standardize.quarterly import derive_quarters_corp

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS is_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis=:basis AND ss.statement='IS'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type=:basis AND s.version=1 AND s.depreciation IS NULL
      AND s.da_total IS NULL
      AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
      {corp_clause}
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def _revenue(session, rcept: str, basis: str) -> int | None:
    return session.execute(text("""
        SELECT MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis=:b
    """), {"r": rcept, "b": basis}).scalar()


def sync_expense_nature(corps=None, year_min: int = 2024, basis: str = "consolidated") -> dict:
    """corp 한정 비용성격 주석 D&A 복원 + 재표준화. corps=None 이면 전체(백필용).

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
            rev = _revenue(session, t.is_rcept, basis)
            facts = extract_expense_nature_facts(
                t.file_path, rcept_no=t.is_rcept, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                basis=basis, revenue_ref=rev,
            )
            if not facts:
                continue
            affected[t.corp_code] = None
            stored += store_facts(session, facts)
        session.commit()

    # R 불변(note 는 source 선택 무관) → S→Q→C 재전파(누적 std_v2 + 이산분기 + 달력뷰까지 반영).
    n_std = n_fail = 0
    for corp in affected:
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                derive_quarters_corp(session, corp)
                calendarize_corp(session, corp)
                session.commit()
        except Exception:  # noqa: BLE001 — 개별 corp 실패 격리(비치명)
            n_fail += 1
    return {"targets": len(targets), "corps": len(affected), "facts": stored,
            "std_recalc": n_std, "fail": n_fail}
