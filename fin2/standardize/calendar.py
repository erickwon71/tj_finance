"""
PRD 03 §5.3 — Layer 2 달력 정규화(calendarization).

Layer 1(std_financials_v2) 의 **이산분기**(is_discrete, period_end 보유)를 period_end 로 달력
분기에 재배열·합산해 전 기업 12월 달력기준으로 통일한다. **파생·Gate B 비대상**.

규칙(PRD §5.3):
  - 매핑: period_end 월 → 달력분기. {3→CQ1, 6→CQ2, 9→CQ3, 12→CQ4}. 비정렬(2/5/8/11월 등)
    period_end 는 **달력화 불가** → 스킵(not_calendarizable).
  - flow(IS/CF): CQn = 그 달력분기 이산분기 값. CY = ΣCQ1..CQ4 (4개 완비 시만; 아니면 미생성).
  - stock(BS): 합산 금지. CQn = 그 분기말 잔액. CY = 12-31 스냅샷(=CQ4 잔액).
  - derivation: native(12월결산=달력=회계) / recomposed(비12월=2 회계연도 합성) / partial(미사용:
    CY 는 완비 시만 생성).
  - native 검증(공짜): 12월결산사 CY flow == 보고 FY(반올림 내) → Layer 1 대조.
"""
from __future__ import annotations

from datetime import date, datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialCalendar
from fin2.standardize.quarterly import _FLOW_COLS, _STOCK_COLS

# period_end 월 → 달력분기 토큰. 달력분기말만(3/6/9/12) 정렬.
_MONTH_CQ = {3: "CQ1", 6: "CQ2", 9: "CQ3", 12: "CQ4"}
_CQ_ORDER = ("CQ1", "CQ2", "CQ3", "CQ4")
_PK = ("corp_code", "calendar_year", "calendar_period", "statement_type", "version")
_CARRY = ("is_ifrs",)


def _corp_fiscal_month(session, corp_code: str) -> int | None:
    return session.execute(text(
        "SELECT fiscal_month FROM corporations WHERE corp_code = :c"), {"c": corp_code}).scalar()


def _load_discrete(session, corp_code: str, basis: str):
    """이산분기(is_discrete=True, NOT is_stub) → period_end 보유 행 목록."""
    rows = session.execute(text("""
        SELECT * FROM std_financials_v2
        WHERE corp_code = :c AND statement_type = :b AND version = 1
          AND is_discrete = true AND NOT COALESCE(is_stub, false)
          AND period_end IS NOT NULL
    """), {"c": corp_code, "b": basis}).fetchall()
    return [dict(r._mapping) for r in rows]


def _cq_record(corp_code, basis, cyear, cq, src, derivation) -> dict:
    """달력분기(CQ) 레코드 = 그 이산분기 값 직배치(flow·stock 그대로)."""
    rec = {
        "corp_code": corp_code, "calendar_year": cyear, "calendar_period": cq,
        "statement_type": basis, "version": 1,
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


def _cy_record(corp_code, basis, cyear, quarters: dict, derivation) -> dict:
    """달력연도(CY) 레코드. flow=ΣCQ, stock=CQ4(12-31) 스냅샷. 4분기 완비 가정."""
    cq4 = quarters["CQ4"]
    rec = {
        "corp_code": corp_code, "calendar_year": cyear, "calendar_period": "CY",
        "statement_type": basis, "version": 1,
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


def calendarize_corp(session, corp_code: str) -> int:
    """corp 의 이산분기를 달력분기/연도로 정규화·upsert. 반환=레코드 수."""
    fiscal_month = _corp_fiscal_month(session, corp_code)
    written = 0
    for basis in ("consolidated", "separate"):
        discrete = _load_discrete(session, corp_code, basis)
        if not discrete:
            continue
        # (calendar_year, CQ) → 이산분기 행. 달력분기말 정렬분만.
        cq_map: dict[tuple, dict] = {}
        for r in discrete:
            cq = _MONTH_CQ.get(r["period_end"].month)
            if cq is None:
                continue  # 비정렬 = not_calendarizable → 스킵
            cq_map[(r["period_end"].year, cq)] = r
        if not cq_map:
            continue
        derivation = "native" if fiscal_month == 12 else "recomposed"

        batch: list[dict] = []
        for (cyear, cq), src in cq_map.items():
            batch.append(_cq_record(corp_code, basis, cyear, cq, src, derivation))
        # CY: 그 달력연도 CQ1..CQ4 완비 시만.
        for cyear in sorted({cy for (cy, _q) in cq_map}):
            quarters = {q: cq_map.get((cyear, q)) for q in _CQ_ORDER}
            if all(quarters[q] is not None for q in _CQ_ORDER):
                batch.append(_cy_record(corp_code, basis, cyear, quarters, derivation))

        stmt = insert(StdFinancialCalendar).values(batch)
        update_cols = {c.name: stmt.excluded[c.name]
                       for c in StdFinancialCalendar.__table__.columns if c.name not in _PK}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_calendar", set_=update_cols)
        session.execute(stmt)
        written += len(batch)
    if written:
        logger.info(f"[calendar] corp={corp_code} — 달력행 {written}레코드")
    return written
