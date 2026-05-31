"""
fin2 S-레이어 조립: statement_source 선택 → fact_v2 수집 → 규칙엔진 → std_financials_v2.

(corp, fy, period, basis) 마다:
  1) statement_source 에서 BS/IS/CF source filing 조회.
  2) 각 statement source 에서 해당 접두어 canonical 의 col0 값 수집(중복 max-abs).
     + D&A 보조: 선택 source 들의 note./is./cf. 감가상각 canonical 합산용 수집.
  3) rules.run_rules 로 std 컬럼 산출.
  4) period_end 추정 · shares_out 조회 · DQ(항등식+교차연도) · std_financials_v2 upsert.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialV2
from fin2.standardize.rules import (
    StdContext, run_rules, validate_equations, VALUE_COLS,
    _DEP_CANON, _AMORT_CANON, _DA_TOTAL_CANON,
)

_PREFIX = {"BS": "bs.", "IS": "is.", "CF": "cf."}
_FP_MONTH_DAY = {"FY": (12, 31), "H1": (6, 30), "Q1": (3, 31), "Q3": (9, 30), "Q2": (6, 30), "Q4": (12, 31)}
_DA_SUPP = set(_DEP_CANON) | set(_AMORT_CANON) | set(_DA_TOTAL_CANON)


def _collect(session, basis: str, sources: dict[str, str]) -> dict[str, int]:
    """선택 source 들에서 canonical→value(원, 중복 max-abs) 수집."""
    canon: dict[str, int] = {}

    def _merge(c, v):
        if v is None:
            return
        if c not in canon or abs(v) > abs(canon[c]):
            canon[c] = v

    for stmt, rcept in sources.items():
        rows = session.execute(text("""
            SELECT canonical_account, amount_won FROM fact_v2
            WHERE rcept_no = :r AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account LIKE :p
        """), {"r": rcept, "b": basis, "p": _PREFIX[stmt] + "%"}).fetchall()
        for c, v in rows:
            _merge(c, v)

    # D&A 보조: note./is./cf. 감가상각 — 선택 source 들의 union 에서
    union = list({r for r in sources.values()})
    if union:
        rows = session.execute(text("""
            SELECT canonical_account, amount_won FROM fact_v2
            WHERE rcept_no = ANY(:rs) AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account = ANY(:cs)
        """), {"rs": union, "b": basis, "cs": list(_DA_SUPP)}).fetchall()
        for c, v in rows:
            _merge(c, v)
    return canon


def _period_end(session, corp_code: str, fiscal_year: int, fiscal_period: str) -> date | None:
    """period_end 추정. 비12월 결산은 corporations.fiscal_month 로 FY 말일 보정."""
    md = _FP_MONTH_DAY.get(fiscal_period, (12, 31))
    try:
        if fiscal_period == "FY":
            fm = session.execute(text(
                "SELECT fiscal_month FROM corporations WHERE corp_code=:c"
            ), {"c": corp_code}).scalar() or 12
            import calendar
            last = calendar.monthrange(fiscal_year, fm)[1]
            return date(fiscal_year, fm, last)
        return date(fiscal_year, md[0], md[1])
    except Exception:
        return None


def _shares_out(session, corp_code: str, period_end: date | None) -> int | None:
    if not period_end:
        return None
    row = session.execute(text("""
        SELECT shares_out FROM stock_prices
        WHERE stock_code = (SELECT stock_code FROM corporations WHERE corp_code = :cc)
          AND shares_out IS NOT NULL
          AND trade_date BETWEEN :d1 AND :d2
        ORDER BY ABS(trade_date - :target) ASC LIMIT 1
    """), {"cc": corp_code, "d1": period_end - timedelta(days=30),
           "d2": period_end + timedelta(days=7), "target": period_end}).fetchone()
    return row[0] if row else None


def _dq_cross_year(session, corp_code: str, basis: str, col: dict) -> int:
    """교차연도 이상값(중앙값 대비 200x→DQ3, 30x→DQ2). std_financials_v2 기준."""
    dq = 1
    for c, lim_err, lim_warn in (("revenue", 200, 30), ("total_assets", 200, 30)):
        nv = col.get(c)
        if not nv or nv <= 0:
            continue
        med = session.execute(text(f"""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {c})
            FROM std_financials_v2
            WHERE corp_code=:cc AND statement_type=:st AND fiscal_period='FY'
              AND {c}>0 AND version=1 AND data_quality<3
        """), {"cc": corp_code, "st": basis}).scalar()
        if med and med >= 1_000_000_000:
            ratio = nv / med
            if ratio > lim_err or ratio < 1.0 / lim_err:
                return 3
            if ratio > lim_warn or ratio < 1.0 / lim_warn:
                dq = max(dq, 2)
    return dq


def standardize_corp(session, corp_code: str, fiscal_year: int | None = None) -> int:
    """statement_source 를 읽어 std_financials_v2 upsert. 반환=레코드 수."""
    fy_clause = "AND fiscal_year = :fy" if fiscal_year is not None else ""
    params: dict = {"corp": corp_code}
    if fiscal_year is not None:
        params["fy"] = fiscal_year

    # (fy, fp, basis) → {statement: rcept}
    rows = session.execute(text(f"""
        SELECT fiscal_year, fiscal_period, basis, statement, source_rcept_no, has_anchor
        FROM statement_source
        WHERE corp_code = :corp {fy_clause}
    """), params).fetchall()
    if not rows:
        logger.warning(f"[standardize2] statement_source 없음: corp={corp_code} fy={fiscal_year}")
        return 0

    groups: dict[tuple, dict[str, str]] = {}
    for r in rows:
        key = (r.fiscal_year, r.fiscal_period, r.basis)
        groups.setdefault(key, {})[r.statement] = r.source_rcept_no

    written = 0
    for (fy, fp, basis), sources in groups.items():
        canon = _collect(session, basis, sources)
        ctx = StdContext(corp_code=corp_code, fiscal_year=fy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)

        period_end = _period_end(session, corp_code, fy, fp)
        shares_out = _shares_out(session, corp_code, period_end)
        # is_ifrs: filings 에 컬럼 없음 → 현재 None(추후 fact_v2 source_format/DocumentMeta 에서 도출).
        is_ifrs = None

        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col) if fp == "FY" else 1)

        record = {
            "corp_code": corp_code, "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": basis, "version": 1,
            "period_end": period_end, "is_ifrs": is_ifrs,
            "data_quality": dq,
            "bs_rcept": sources.get("BS"), "is_rcept": sources.get("IS"), "cf_rcept": sources.get("CF"),
            "applied_rules": ctx.applied, "shares_out": shares_out,
            "calculated_at": datetime.utcnow(),
            **{c: ctx.col.get(c) for c in VALUE_COLS},
        }
        stmt = insert(StdFinancialV2).values(record)
        update_cols = {k: stmt.excluded[k] for k in record if k not in
                       ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version")}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_v2", set_=update_cols)
        session.execute(stmt)
        written += 1

    logger.info(f"[standardize2] corp={corp_code} fy={fiscal_year or 'all'} — std_v2 {written}레코드")
    return written
