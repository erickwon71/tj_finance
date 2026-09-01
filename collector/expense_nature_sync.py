"""신규/증분 보고서 '비용의 성격별 분류' D&A 복원 — collect_new 파이프라인 영속화 (Phase 4).

collector/cf_da_sync.py 의 정확한 클론. 차이:
  - 소스 statement='IS'(비용성격 주석은 손익 관련 절 — IS 승자 rcept + file_path 로 파싱/적재).
  - 추출기 = fin2.extract.expense_nature.extract_expense_nature_facts.
  - cf_da_sync 다음에 돌아 **여전히 depreciation IS NULL** 인 잔여만 타겟 → 이중 계상 방지
    (cf_da 가 CF 경로로 채우지 못한 보고서에서만 비용성격 주석으로 D&A 를 보충).

순서: 추출→store_facts(기업 단위 commit). extended_financials 소관 fact_v2 upsert 만
수행한다.

★2026-08-30(valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5 순서1) —
std_v2 재표준화(standardize_corp/derive_quarters_corp/calendarize_corp) 호출을
제거했다. cf_da_sync.py 와 동일 사유(§모듈 docstring 참고) — std_v2 소비자가 없다.

★2026-09-01(fact_v2/std_v2 GC 트랙, `std_financials_v2` DROP) — cf_da_sync.py 와 동일
사유로 `_TARGET_SQL`을 std_financials_v2 → v3 로 전환(이 모듈도 `depreciation IS NULL`
셀렉터로 std_v2 를 읽고 있었다). `s.version=1` 조건 삭제(v3 엔 없음).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.expense_nature import extract_expense_nature_facts
from fin2.extract.xbrl import store_facts

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS is_rcept, dt.file_path
    FROM std_financials_v3 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis=:basis AND ss.statement='IS'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type=:basis AND s.depreciation IS NULL
      AND s.da_total IS NULL
      -- 비용성격 주석은 연간(FY) 총액 → FY 만 타겟. interim(H1/Q1/Q3) da_total 은 표준화의
      -- 분기 이산화(derive_quarters_corp)가 담당한다. FY 만 걸어야 완료판정(FY-only)과 정합하고,
      -- FY 는 끝났는데 interim 만 NULL 인 corp 가 타겟에 영구 잔류해 매 밤 재처리되는 것을 막는다.
      AND s.fiscal_period = 'FY'
      AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
      {corp_clause}
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def sync_expense_nature(corps=None, year_min: int = 2024, basis: str = "consolidated",
                        max_corps: int | None = None) -> dict:
    """corp 한정 비용성격 주석 D&A 복원(fact_v2 upsert 만). corps=None 이면 전체(백필용).

    **기업당 원자적 처리**: 각 corp 의 추출→store_facts→commit 을 그 corp 단위로 끝낸다 —
    중단돼도 이미 처리된 corp 는 da_total 이 채워져(NOT NULL) 다음 실행의 타겟에서 자동
    제외되므로, DB 자체가 체크포인트가 되어 **처음부터 다시 하지 않는다**.
    (예전엔 전체 추출을 단일 거대 트랜잭션 1회 commit 해, 중단 시 그날 작업 전부 롤백됐다.)

    max_corps: 한 실행에서 처리할 최대 기업 수(야간 잡의 실행시간을 유계로 — 나머지는 다음 밤).
               None 이면 대상 전부.

    반환: {targets, corps, facts, std_recalc, fail}. std_recalc/fail 은 std_v2 재전파가
    제거돼(위 모듈 docstring 참고) 항상 0 — 호출부 호환을 위해 필드는 유지."""
    corp_clause = "AND s.corp_code = ANY(:corps)" if corps else ""
    sql = _TARGET_SQL.format(corp_clause=corp_clause)
    params: dict = {"basis": basis, "ymin": year_min}
    if corps:
        params["corps"] = list(corps)

    with get_session() as session:
        targets = session.execute(text(sql), params).fetchall()

    # (corp → [해당 corp 의 (fy,fp,rcept,path) 타겟들]) 로 그룹핑해 기업단위로 처리.
    by_corp: dict[str, list] = {}
    for t in targets:
        by_corp.setdefault(t.corp_code, []).append(t)
    corp_list = list(by_corp)
    if max_corps is not None:
        corp_list = corp_list[:max_corps]

    stored = affected = 0
    for corp in corp_list:
        try:
            # 이 corp 의 모든 타겟(fy,fp) 추출 → store_facts → commit(기업 단위 원자).
            # ★2026-08-30: 여기서 이어 돌던 std_v2 재표준화(standardize_corp/
            # derive_quarters_corp/calendarize_corp) 호출을 제거했다 — 소비자 없음
            # (모듈 docstring 참고).
            corp_facts = 0
            with get_session() as session:
                for t in by_corp[corp]:
                    if not t.file_path or not Path(t.file_path).exists():
                        continue
                    facts = extract_expense_nature_facts(
                        t.file_path, rcept_no=t.is_rcept, corp_code=t.corp_code,
                        report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                        basis=basis,
                    )
                    if facts:
                        corp_facts += store_facts(session, facts)
                session.commit()
            if corp_facts == 0:
                continue
            affected += 1
            stored += corp_facts
        except Exception:  # noqa: BLE001 — 개별 corp 실패 격리(비치명), 다음 corp 계속
            pass
    return {"targets": len(targets), "corps": affected, "facts": stored,
            "std_recalc": 0, "fail": 0}
