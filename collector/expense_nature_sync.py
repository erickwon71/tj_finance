"""신규/증분 보고서 '비용의 성격별 분류' 주석 복원 — collect_new 파이프라인 영속화 (Phase 4).

collector/cf_da_sync.py 의 정확한 클론이었다. 차이:
  - 소스 statement='IS'(비용성격 주석은 손익 관련 절 — IS 승자 rcept + file_path 로 파싱/적재).
  - 추출기 = fin2.extract.expense_nature.extract_expense_nature_facts.
  - cf_da_sync 다음에 돌아 **여전히 depreciation IS NULL** 인 잔여만 타겟(이중 계상 방지 목적
    이었음 — 아래 ★2026-09-01 Track 2 은퇴 이후로는 사실상 잔여 타겟팅일 뿐).

★2026-09-01(fact_v2 GC 트랙, `docs/plans/factv2_sync_scripts_migration_design_2026-09-01.md`) —
이 모듈이 뽑는 canonical 은 두 목적지로 갈라졌다(설계문서 §2):
  - Track 1(이 커밋에서 구현): `note.employee_benefits`/`note.raw_materials_used`
    (EXTENDED_CATALOG 등재 항목) → `extended_facts_v3` 직접 upsert
    (`fin2.extract.xbrl.store_extended_facts_v3`). §4-2 뷰 재설계(commit `243e9ee`)
    이후 `extended_financials` 뷰가 `fact_v2` 를 더 이상 읽지 않게 되면서 이 두
    canonical 이 **조용히 앱에서 사라져 있었다**(실측: `extended_facts_v3`에 `note.%`
    0건) — 이 이식이 그 회귀도 같이 고친다.
  - Track 2(은퇴, 미구현): `note.depreciation`/`amortization`/`rou_depreciation`/
    `note.da_total` — `fact_v2` 의 유일 소비자였던 `std_financials_v2`(std_v2 규칙엔진)가
    이미 DROP돼 죽은 쓰기였음이 실측으로 확인됐다(`fin2/standardize/build.py::
    standardize_corp()` RuntimeError 가드). v3 쪽 D&A(`fin2/layer3/note_da.py`)는
    `note_lines`만 읽고 `fact_v2`를 안 읽어 애초에 이 값을 쓸 방법이 없었다 —
    사용자 결정으로 "은퇴" 채택. 이 canonical 들은 이제 **추출은 하되 어디에도
    저장하지 않는다**(store_facts/store_extended_facts_v3 둘 다 호출 안 함).

★잔여 한계(범위 밖, 재설계 안 함): `_TARGET_SQL`이 여전히 `depreciation IS NULL`
기준으로 corp 을 고른다 — 원래 목적(D&A 보충)이 은퇴됐어도 그대로 뒀다. 그 결과
employee_benefits/raw_materials_used 도 "D&A 갭이 있는 corp"으로만 타겟이 좁혀진다
(카탈로그 전체 커버리지를 노리려면 별도 타겟팅 재설계 필요 — 이번 트랙 범위 밖).

★2026-08-30(valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5 순서1) —
std_v2 재표준화(standardize_corp/derive_quarters_corp/calendarize_corp) 호출을
제거했다. cf_da_sync.py 와 동일 사유(§모듈 docstring 참고) — std_v2 소비자가 없다.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.expense_nature import extract_expense_nature_facts
from fin2.extract.xbrl import store_extended_facts_v3

# Track 1(extended_facts_v3) 목적지 canonical만 — 나머지(D&A 계열)는 Track 2 은퇴로 폐기.
_EXTENDED_CATALOG_CANONICALS = frozenset({"note.employee_benefits", "note.raw_materials_used"})

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
    """corp 한정 비용성격 주석 복원. corps=None 이면 전체(백필용).

    ★2026-09-01(Track 2 은퇴) — 추출 자체는 예전과 동일(D&A 갭 corp 타겟, cf_da_sync
    다음 잔여만)하지만, 저장은 `_EXTENDED_CATALOG_CANONICALS`(employee_benefits/
    raw_materials_used)만 `extended_facts_v3`에 한다. D&A 계열(depreciation/
    amortization/rou_depreciation/da_total)은 추출됐다가 그대로 버려진다 — 저장할
    유효 목적지가 없기 때문(모듈 docstring 참고).

    **기업당 원자적 처리**: 각 corp 의 추출→store→commit 을 그 corp 단위로 끝낸다.
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
            # 이 corp 의 모든 타겟(fy,fp) 추출 → extended_facts_v3 upsert → commit(기업 단위 원자).
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
                    # Track 2 은퇴(모듈 docstring) — D&A 계열은 여기서 걸러 버린다.
                    ext_facts = [f for f in facts
                                if f.canonical_account in _EXTENDED_CATALOG_CANONICALS]
                    if ext_facts:
                        corp_facts += store_extended_facts_v3(session, ext_facts)
                session.commit()
            if corp_facts == 0:
                continue
            affected += 1
            stored += corp_facts
        except Exception:  # noqa: BLE001 — 개별 corp 실패 격리(비치명), 다음 corp 계속
            pass
    return {"targets": len(targets), "corps": affected, "facts": stored,
            "std_recalc": 0, "fail": 0}
