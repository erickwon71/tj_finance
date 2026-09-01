"""
PRD 03 §5.1/§5.3 — v3 경로: 이산분기 파생 + 달력 정규화를 하나로 병합.

`std_financials_v2` 를 읽고 쓰던 `quarterly.py::derive_quarters_corp()`(as-filed 누적행 →
이산분기)와 `calendar.py::calendarize_corp()`(이산분기 → 달력분기)는 std_v2 DROP(2026-09-01)
으로 죽은 경로가 됐다(RuntimeError 가드). 이 모듈은 같은 계산을 `std_financials_v3` 를
소스로 다시 배선하되, **이산분기를 DB에 저장하지 않고 메모리 dict 로만** 만들어 바로
`calendar.py::_cq_record()`/`_cy_record()` 에 먹인다 — 최종 저장 대상은
`std_financials_calendar` 하나뿐이다.

계산 로직(`quarterly.py::_build_discrete()`, `calendar.py::_cq_record()`/`_cy_record()`)은
둘 다 이미 순수 함수라 **한 글자도 바뀌지 않고 그대로 재사용**한다 — 바뀌는 건 입력
소스(std_financials_v2 SELECT → std_financials_v3 SELECT)와 중간 저장 단계 제거뿐.

`std_financials_v3` 는 PK 하나뿐이라(is_stub/is_discrete/version 없음, §5-a 결정) 저장된
행이 곧 as-filed 누적행 — v2 의 `NOT is_stub AND NOT is_discrete` 필터가 애초에 불필요하다.
`version` 개념도 v3 경로엔 불필요(열린질문 §4-2 결론 — v3 자신의 신규테이블+컷오버 선례가
row-level 버전 플래그를 대체) → `std_financials_calendar` 에는 상수 `version=1` 로만 쓴다.

배경·조사근거: docs/plans/calendar_v3_migration_scoping_2026-09-02.md
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialCalendar
from fin2.standardize.quarterly import _QUARTER_SPEC, _build_discrete
from fin2.standardize.calendar import (
    _MONTH_CQ, _CQ_ORDER, _corp_fiscal_month, _is_calendarizable_end,
    _cq_record, _cy_record,
)


def _load_asfiled_v3(session, corp_code: str, basis: str) -> dict[tuple[int, str], dict]:
    """as-filed 누적행(std_financials_v3) → {(fiscal_year, fiscal_period): row dict}.

    v3 는 PK 하나뿐(corp_code, fiscal_year, fiscal_period, statement_type) — 저장된 행이
    곧 as-filed 누적행이라 v2 의 `NOT is_stub AND NOT is_discrete` 필터 불요.
    `is_ifrs` 는 v3 소스에 컬럼 자체가 없다 — `collector/db.py::standard_financials` 뷰가
    이미 쓰는 관례(2015+ 전량 K-IFRS 의무화 이후, "TRUE AS is_ifrs")를 그대로 따라 상수를
    채운다. `_build_discrete()` 가 참조하는 `bs_rcept`/`is_rcept`/`cf_rcept`/`applied_rules`
    는 v3 에 없어 `dict.get()` 이 조용히 None 을 반환 — crash 없음(quarterly.py 쪽에서
    이 값들은 opinc_kifrs provenance 마킹에만 쓰이고 그 마킹은 `std_financials_calendar`
    에 컬럼 자체가 없어 소비되지 않는다).
    """
    rows = session.execute(text("""
        SELECT * FROM std_financials_v3
        WHERE corp_code = :c AND statement_type = :b
          AND fiscal_period IN ('Q1', 'H1', 'Q3', 'FY')
    """), {"c": corp_code, "b": basis}).fetchall()
    out: dict[tuple[int, str], dict] = {}
    for r in rows:
        d = dict(r._mapping)
        d["is_ifrs"] = True
        out[(d["fiscal_year"], d["fiscal_period"])] = d
    return out


def calendarize_corp_v3(session, corp_code: str) -> int:
    """corp 의 std_financials_v3 as-filed 누적행 → (메모리 이산분기) → 달력분기/연도 upsert.

    반환=쓴 레코드 수. `std_financials_calendar` 의 version 은 상수 1.
    """
    fiscal_month = _corp_fiscal_month(session, corp_code)
    written = 0
    for basis in ("consolidated", "separate"):
        # delete-then-insert: 기재정정으로 이산분기의 period_end 가 바뀌면 예전 달력분기가
        # 유령행으로 남으므로(calendar.py::calendarize_corp 와 동일 근거) 지운 뒤 새로 채운다.
        session.execute(text(
            "DELETE FROM std_financials_calendar "
            "WHERE corp_code = :c AND statement_type = :b AND version = 1"),
            {"c": corp_code, "b": basis})

        asfiled = _load_asfiled_v3(session, corp_code, basis)
        if not asfiled:
            continue

        # 1) 이산분기 — DB 저장 없이 메모리 dict 로만 조립(quarterly.py 로직 그대로).
        years = sorted({fy for (fy, _fp) in asfiled})
        discrete: list[dict] = []
        for fy in years:
            for q, (end_fp, sub_fp) in _QUARTER_SPEC.items():
                end_row = asfiled.get((fy, end_fp))
                if end_row is None:
                    continue
                sub_row = asfiled.get((fy, sub_fp)) if sub_fp else None
                if sub_fp is not None and sub_row is None:
                    continue  # 차감행 결측 → 미생성
                rec = _build_discrete(end_row, sub_row, q)
                if rec is not None:
                    discrete.append(rec)
        if not discrete:
            continue

        # 2) 달력 정규화 — calendar.py::calendarize_corp 와 동일 로직, 소스만 메모리 discrete
        #    (그쪽은 std_financials_v2 SELECT 로 다시 읽지만, 여긴 위에서 만든 걸 바로 씀).
        cq_map: dict[tuple, dict] = {}
        for r in discrete:
            pe = r.get("period_end")
            if pe is None or not _is_calendarizable_end(pe):
                continue  # 결측·미래 분기말 = 실제 데이터 불가 → 스킵
            cq = _MONTH_CQ.get(pe.month)
            if cq is None:
                continue  # 비정렬(달력분기말 아님) = not_calendarizable → 스킵
            cq_map[(pe.year, cq)] = r
        if not cq_map:
            continue
        derivation = "native" if fiscal_month == 12 else "recomposed"

        batch: list[dict] = []
        for (cyear, cq), src in cq_map.items():
            batch.append(_cq_record(corp_code, basis, cyear, cq, src, derivation))
        # CY: 그 달력연도 CQ1..CQ4 완비 시만(추정 금지).
        for cyear in sorted({cy for (cy, _q) in cq_map}):
            quarters = {q: cq_map.get((cyear, q)) for q in _CQ_ORDER}
            if all(quarters[q] is not None for q in _CQ_ORDER):
                cy_deriv = ("native"
                            if len({quarters[q]["fiscal_year"] for q in _CQ_ORDER}) == 1
                            else "recomposed")
                batch.append(_cy_record(corp_code, basis, cyear, quarters, cy_deriv))

        session.execute(insert(StdFinancialCalendar).values(batch))
        written += len(batch)

    if written:
        logger.info(f"[calendar_v3] corp={corp_code} — 달력행 {written}레코드")
    return written
