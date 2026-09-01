"""
신규/증분 보고서 D&A note 복원 — collect_new 파이프라인 영속화 (B5).

배경: DART 2024+ Track A 전환으로 연결 현금흐름표 감가상각이 개별 XBRL ACODE 로
태깅되지 않아(집계라인만) fin2/extract/xbrl.py 가 놓친다 → EBITDA/da_total 절벽.
일회성 백필(scripts/fin2_extract_cf_da_consolidated.py)로 과거분은 복원했으나, 추출이
표준 파이프라인에 없어 **신규 보고서는 D&A 를 못 받고 재퇴행**(2026 신규 EBITDA ~11%).

이 모듈은 그 백필과 동일 로직을 **corp 한정**으로 수행: 연결 FY depreciation NULL +
연결 CF source 보유(fy>=year_min) 보고서에 note.* D&A fact 를 하이브리드 복원
(주석 우선·본문 폴백, 단위가드 da/매출∈[0.3%,60%]) → fact_v2 upsert. collect_new 가
매일 신규표준화 corp 에 호출 → fact_v2/extended_financials 소관 D&A 갭 보완.

주의: depreciation IS NULL(본문 D&A 없는 보고서)만 손대 중복합산을 막는다. upsert idempotent.

★2026-08-30(valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5 순서1) —
std_v2 재표준화(standardize_corp/derive_quarters_corp/calendarize_corp) 호출을
제거했다. std_v2 소비자가 없어져 재전파가 불필요해진 데다, 레거시 note_extractor
경로의 note.da_total 합성 이중계상(§1)이 std_v2에 새로 쓰이는 것도 이걸로 막힌다.
fact_v2 upsert(store_facts)는 extended_financials 소관이라 그대로 유지한다.

★2026-09-01(fact_v2/std_v2 GC 트랙, `std_financials_v2` DROP) — 타겟 셀렉터
(`_TARGET_SQL`)를 std_financials_v2 → v3 로 전환. 위 단락은 std_v2 "재표준화 호출"
얘기라 이 모듈 자체가 std_v2 소비자가 아니라는 뜻이 아니었다 — `_TARGET_SQL`이
`depreciation IS NULL` 판정을 위해 std_v2 를 **읽고는** 있었다(이 파일이 collect_new.py
④ 경로에서 매일 불림). v2 DROP 시점에 뒤늦게 발견해 같이 이식. v3 는 PK 가
(corp_code,fiscal_year,fiscal_period,statement_type) 뿐이라 `s.version=1` 조건은 삭제.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.cf_da import recover_cf_da
from fin2.extract.xbrl import store_facts

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v3 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis=:basis AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type=:basis AND s.depreciation IS NULL
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
    """corp 한정 D&A note 복원(fact_v2 upsert 만). corps=None 이면 전체(백필용).

    반환: {targets, corps, facts, std_recalc, fail}. std_recalc/fail 은 std_v2
    재전파가 제거돼(위 모듈 docstring 참고) 항상 0 — 호출부 호환을 위해 필드는 유지."""
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

    # ★2026-08-30: 여기서 돌던 std_v2 재표준화(standardize_corp/derive_quarters_corp/
    # calendarize_corp) 호출을 제거했다 — 소비자 없음(모듈 docstring 참고).
    return {"targets": len(targets), "corps": len(affected), "facts": stored,
            "std_recalc": 0, "fail": 0}
