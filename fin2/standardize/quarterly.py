"""
PRD 03 §5.1 — 분기 환산(quarterly conversion).

as-filed 누적행(Q1/H1/Q3/FY)에서 **이산분기**(3개월) 행 Q1~Q4 를 파생해 std_financials_v2 에
`is_discrete=True` 로 적재한다. flow(IS/CF)만 차감, stock(BS)은 분기말 스냅샷(불가침).

공식(PRD §5.1):
    Q1(이산) = Q1누적
    Q2       = H1누적 − Q1누적
    Q3(이산) = Q3누적 − H1누적
    Q4       = FY − Q3누적

원자성: 각 이산행은 `period_end`(3/6/9/12월말) 보유 → Layer 2 calendarization(§5.3)의 원자.
결측: 차감 구성요소(누적행) 중 하나라도 없으면 그 분기 **미생성**. 컬럼별로 한쪽이 None 이면
그 컬럼만 None(추정·보간 금지). 누적행과 **공존**(소비자가 둘 다 조회).

설계: 누적행은 telescoping 으로 ΣQ=FY 가 항등 성립(파생이 누적에서 나옴) → 자기검증은
누적행 단조성(별도 검증됨)에 위임. BS·Gate B·기본 view 불가침(is_discrete 제외 필터).
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialV2
from fin2.standardize.rules import _BS_MAP, _IS_MAP, _CF_MAP

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

_PK = ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version",
       "is_stub", "is_discrete")


def _load_asfiled(session, corp_code: str, basis: str, fiscal_year: int | None,
                  version: int = 1):
    """as-filed 누적행(is_discrete=False, NOT is_stub) → {(fy, fp): row dict}."""
    fy_clause = "AND fiscal_year = :fy" if fiscal_year is not None else ""
    params: dict = {"c": corp_code, "b": basis, "v": version}
    if fiscal_year is not None:
        params["fy"] = fiscal_year
    rows = session.execute(text(f"""
        SELECT * FROM std_financials_v2
        WHERE corp_code = :c AND statement_type = :b AND version = :v
          AND NOT COALESCE(is_stub, false) AND NOT COALESCE(is_discrete, false)
          {fy_clause}
    """), params).fetchall()
    return {(r.fiscal_year, r.fiscal_period): dict(r._mapping) for r in rows}


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
    return rec


def derive_quarters_corp(session, corp_code: str, fiscal_year: int | None = None,
                         version: int = 1) -> int:
    """corp 의 as-filed 누적행에서 이산분기 Q1~Q4 파생·upsert. 반환=레코드 수.
    version: 소비계층 버전(기본 1). Phase C 재구축은 version=2."""
    written = 0
    for basis in ("consolidated", "separate"):
        asfiled = _load_asfiled(session, corp_code, basis, fiscal_year, version)
        if not asfiled:
            continue
        years = sorted({fy for (fy, _fp) in asfiled})
        batch: list[dict] = []
        for fy in years:
            for q, (end_fp, sub_fp) in _QUARTER_SPEC.items():
                end_row = asfiled.get((fy, end_fp))
                if end_row is None:
                    continue
                sub_row = asfiled.get((fy, sub_fp)) if sub_fp else None
                if sub_fp is not None and sub_row is None:
                    continue  # 차감행 결측 → 미생성
                rec = _build_discrete(end_row, sub_row, q, version)
                if rec is not None:
                    batch.append(rec)
        if not batch:
            continue
        stmt = insert(StdFinancialV2).values(batch)
        update_cols = {c.name: stmt.excluded[c.name] for c in StdFinancialV2.__table__.columns
                       if c.name not in _PK}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_v2", set_=update_cols)
        session.execute(stmt)
        written += len(batch)
    if written:
        logger.info(f"[quarterly] corp={corp_code} fy={fiscal_year or 'all'} — 이산분기 {written}레코드")
    return written
