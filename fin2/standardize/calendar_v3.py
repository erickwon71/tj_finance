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

from datetime import date, datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialCalendar
from fin2.standardize.rules import _BS_MAP, _IS_MAP, _CF_MAP

# ★2026-10-03 — 아래 헬퍼들은 v2 체인(fin2/standardize/quarterly.py·calendar.py, std_financials_v2
# 기반)이 삭제되면서 이 모듈로 옮겨졌다. 이산분기 조립·달력분기 레코드 로직 자체는 그대로다.
# flow = IS + CF 값컬럼 + 파생 flow(선형 합산성). 이산분기는 차감.
_FLOW_COLS: tuple[str, ...] = tuple(sorted(
    set(_IS_MAP.values()) | set(_CF_MAP.values())
    | {"capex", "depreciation", "amortization", "da_total", "ebitda", "fcf"}
))
# stock = BS 값컬럼 + BS 파생(net_debt) + 시점값(shares_out). 분기말 스냅샷(차감 금지).
_STOCK_COLS: tuple[str, ...] = tuple(sorted(
    set(_BS_MAP.values()) | {"net_debt", "shares_out"}
))

# 이산분기 → (말 누적행 fp, 차감 누적행 fp | None)
#   Q1 = Q1                  (차감 없음, Q1누적=3개월)
#   Q2 = H1 − Q1
#   Q3 = Q3누적 − H1
#   Q4 = FY − Q3누적
_QUARTER_SPEC: dict[str, tuple[str, str | None]] = {
    "Q1": ("Q1", None),
    "Q2": ("H1", "Q1"),
    "Q3": ("Q3", "H1"),
    "Q4": ("FY", "Q3"),
}


def _build_discrete(end_row: dict, sub_row: dict | None, fp: str,
                    version: int = 1) -> dict | None:
    """한 이산분기 레코드 조립. end/sub = 누적행. sub None 이면 차감 없음(Q1)."""
    rec: dict = {
        "corp_code": end_row["corp_code"], "fiscal_year": end_row["fiscal_year"],
        "fiscal_period": fp, "statement_type": end_row["statement_type"],
        "version": version, "is_stub": False, "is_discrete": True,
        # 시점·연원은 말(end) 누적행에서 승계.
        "period_end": end_row.get("period_end"), "is_ifrs": end_row.get("is_ifrs"),
        "bs_rcept": end_row.get("bs_rcept"), "is_rcept": end_row.get("is_rcept"),
        "cf_rcept": end_row.get("cf_rcept"),
        "applied_rules": ["quarterly_derived"],
        "calculated_at": datetime.utcnow(),
    }
    # stock(BS)·시점값 = 분기말 스냅샷(end 누적행 그대로).
    for c in _STOCK_COLS:
        rec[c] = end_row.get(c)
    # flow = end − sub (둘 다 있을 때만; 한쪽 None → 그 컬럼 None).
    n_flow = 0
    for c in _FLOW_COLS:
        ev = end_row.get(c)
        if sub_row is None:
            rec[c] = ev
        elif ev is not None and sub_row.get(c) is not None:
            rec[c] = ev - sub_row[c]
        else:
            rec[c] = None
        if rec[c] is not None:
            n_flow += 1
    # flow 가 전무하면(IS/CF 데이터 없음) 이산분기 의미 없음 → 미생성.
    if n_flow == 0:
        return None
    # data_quality: 결측 구성요소로 일부 flow 가 None 이면 경고(2), 아니면 정상(1).
    rec["data_quality"] = 1 if all(rec.get(c) is not None
                                   for c in _FLOW_COLS if end_row.get(c) is not None) else 2
    # provenance 승계: 이산분기 영업이익은 K-IFRS as-filed 행에서 파생 → opinc_kifrs 마크 전파.
    if rec.get("operating_income") is not None and end_row.get("applied_rules") \
            and "opinc_kifrs" in end_row["applied_rules"]:
        rec["applied_rules"] = rec["applied_rules"] + ["opinc_kifrs"]
    return rec


# period_end 월 → 달력분기 토큰. 달력분기말만(3/6/9/12) 정렬.
_MONTH_CQ = {3: "CQ1", 6: "CQ2", 9: "CQ3", 12: "CQ4"}
_CQ_ORDER = ("CQ1", "CQ2", "CQ3", "CQ4")
_CARRY = ("is_ifrs",)


def _corp_fiscal_month(session, corp_code: str) -> int | None:
    return session.execute(text(
        "SELECT fiscal_month FROM corporations WHERE corp_code = :c"), {"c": corp_code}).scalar()


def _is_calendarizable_end(period_end: date, today: date | None = None) -> bool:
    """달력분기는 해당 분기말(period_end)이 지나야만 구성 가능하다.

    period_end 가 미래(=아직 끝나지 않은 분기)면 실제 데이터가 존재할 수 없으므로
    달력화 대상에서 제외한다. (오프셋 결산·시드성 데이터가 미래 분기말을 갖는 경우 방어.)
    """
    return period_end <= (today or date.today())


def _cq_record(corp_code, basis, cyear, cq, src, derivation, version: int = 1) -> dict:
    """달력분기(CQ) 레코드 = 그 이산분기 값 직배치(flow·stock 그대로)."""
    rec = {
        "corp_code": corp_code, "calendar_year": cyear, "calendar_period": cq,
        "statement_type": basis, "version": version,
        "period_end": src["period_end"], "derivation": derivation,
        "is_complete": False,
        "source_lineage": [[src["fiscal_year"], src["fiscal_period"]]],
        "data_quality": src.get("data_quality") or 0,
        "calculated_at": datetime.utcnow(),
    }
    for c in _CARRY:
        rec[c] = src.get(c)
    for c in _FLOW_COLS:
        rec[c] = src.get(c)
    for c in _STOCK_COLS:
        rec[c] = src.get(c)
    return rec


def _cy_record(corp_code, basis, cyear, quarters: dict, derivation, version: int = 1) -> dict:
    """달력연도(CY) 레코드. flow=ΣCQ, stock=CQ4(12-31) 스냅샷. 4분기 완비 가정."""
    cq4 = quarters["CQ4"]
    rec = {
        "corp_code": corp_code, "calendar_year": cyear, "calendar_period": "CY",
        "statement_type": basis, "version": version,
        "period_end": date(cyear, 12, 31), "derivation": derivation,
        "is_complete": True,
        "source_lineage": [[quarters[q]["fiscal_year"], quarters[q]["fiscal_period"]]
                           for q in _CQ_ORDER],
        "data_quality": max((quarters[q].get("data_quality") or 0) for q in _CQ_ORDER),
        "calculated_at": datetime.utcnow(),
    }
    for c in _CARRY:
        rec[c] = cq4.get(c)
    # flow = ΣCQ (각 분기 그 컬럼이 모두 non-None 일 때만; 하나라도 None → None, 추정 금지).
    for c in _FLOW_COLS:
        vals = [quarters[q].get(c) for q in _CQ_ORDER]
        rec[c] = sum(vals) if all(v is not None for v in vals) else None
    # stock = 12-31 스냅샷(CQ4 잔액).
    for c in _STOCK_COLS:
        rec[c] = cq4.get(c)
    return rec


def _load_asfiled_v3(session, corp_code: str, basis: str) -> dict[tuple[int, str], dict]:
    """as-filed 누적행(std_financials_v3) → {(fiscal_year, fiscal_period): row dict}.

    v3 는 PK 하나뿐(corp_code, fiscal_year, fiscal_period, statement_type) — 저장된 행이
    곧 as-filed 누적행이라 v2 의 `NOT is_stub AND NOT is_discrete` 필터 불요.
    `is_ifrs`(2026-09-08, docs/plans/is_ifrs_v3_design_2026-09-08.md)는 이제 v3에 실제
    컬럼이 있다(`SELECT *`로 이미 딸려온다) — 예전엔 컬럼 자체가 없어 `collector/db.py::
    standard_financials` 뷰가 쓰던 "TRUE 상수" 관례를 여기서도 강제로 흉내냈었지만, 그
    근거(2015+만 있고 전량 IFRS 의무화 이후)가 소급백필로 깨져 폐기됐다. `_build_discrete()`
    가 참조하는 `bs_rcept`/`is_rcept`/`cf_rcept`/`applied_rules`
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
