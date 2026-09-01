"""Layer 3 std_v3 builder (L3-3).

Assembles `std_financials_v3` rows from report_lines (Layer 2) via combine_full,
persisting the direct-mapped metrics plus provenance (source filings, 기재정정
반영 표시, basis fallback, held conflicts).

Grain: (corp_code, fiscal_year, fiscal_period, statement_type=basis). Idempotent
per row (delete-then-insert of the (corp, fy, period, basis) key). Scope of this
prototype = DIRECT_MAP metrics; additive/derived (D&A/EBITDA/debt/capex) later.
"""
from __future__ import annotations

from sqlalchemy import text, delete

from collector.models import StdFinancialV3, ExtendedFactV3
from fin2.layer3.combine import (combine_full, select_canonical_rcepts,
                                 build_merged_lines)
from fin2.standardize.build import _period_end, _future_guard
from fin2.standardize.rules import validate_equations

_VALUE_COLS = (
    "total_assets current_assets cash receivables inventory ppe intangibles "
    "total_liabilities current_liabilities short_term_debt long_term_debt "
    "total_equity controlling_equity retained_earnings trade_payables "
    "revenue cogs gross_profit sga rd_expense operating_income interest_expense "
    "ebt tax_expense net_income controlling_ni cfo cfi cff dividends_paid "
    # enrichment (v3-native): combine 이 산출.
    #   · capex/fcf/net_debt            (2026-07-25)
    #   · depreciation/amortization/da_total/ebitda (2026-07-28, 주석 소스 — fin2/layer3/note_da.py)
    # shares_out 은 여전히 별도 백필 필요(계층2 신설 대상, Phase 2). data_quality/period_end 는
    # _VALUE_COLS 에 안 넣고 build_corp 에서 row 에 직접 대입한다(아래 참고, Phase 1 2026-08-09).
    # ★이 목록에 없는 컬럼은 combine 이 값을 내도 **테이블에 안 들어간다**.
    "capex fcf net_debt depreciation amortization da_total ebitda"
).split()


def _dq_cross_year_v3(session, corp_code: str, basis: str, col: dict) -> int:
    """Cross-year outlier check, ported for std_financials_v3 from
    fin2/standardize/build.py::_dq_cross_year (200x median → DQ3, 30x → DQ2).

    std_v3 has no `version`/`is_stub` columns (unlike std_v2) — key is just
    corp_code + statement_type(basis) + fiscal_period='FY'. Within one build_corp
    call, periods are processed in ascending fiscal_year order in the same session,
    so by the time year Y is checked, prior years' data_quality (this call, this
    session) is already flushed and visible to this raw-SQL SELECT.
    """
    dq = 1
    for c, lim_err, lim_warn in (("revenue", 200, 30), ("total_assets", 200, 30)):
        nv = col.get(c)
        if not nv or nv <= 0:
            continue
        med = session.execute(text(f"""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {c})
            FROM std_financials_v3
            WHERE corp_code=:cc AND statement_type=:st AND fiscal_period='FY'
              AND {c}>0 AND data_quality<3
        """), {"cc": corp_code, "st": basis}).scalar()
        if med and med >= 1_000_000_000:
            ratio = nv / med
            if ratio > lim_err or ratio < 1.0 / lim_err:
                return 3
            if ratio > lim_warn or ratio < 1.0 / lim_warn:
                dq = max(dq, 2)
    return dq


def _select_shares_out(session, corp: str, fy: int, period: str, src: dict) -> int | None:
    """shares_out 정본선택 (Phase 2, 2026-08-09 — 계층2 신설, report_shares_outstanding 조인
    전용, 원문 직접 read 없음: architecture-report-read-layer2-only 준수).

    ① 이 (fy, period) 의 재무제표 정본 filing(src — select_canonical_rcepts 결과)과 **같은
       rcept**에서 보고된 주식수를 우선한다 — 같은 filing 이 낸 숫자끼리 provenance 가
       일관된다. ② 못 찾으면(그 filing 이 섹션 자체를 안 담았거나 파싱 실패) 이 corp+fy+period
       를 보고한 아무 filing 에서나 **가장 최근(rcept_no 최대) 값**으로 폴백 — 여러 filing 이
       같은 기간을 다르게 보고할 때(기재정정 등) 최신 정정을 우선한다는 원칙과 일치.
    """
    primary = (src.get("BS") or src.get("IS") or src.get("CF")) if src else None
    if primary:
        v = session.execute(text(
            "SELECT shares_out FROM report_shares_outstanding WHERE rcept_no=:r"),
            {"r": primary}).scalar()
        if v:
            return v
    return session.execute(text("""
        SELECT shares_out FROM report_shares_outstanding
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
        ORDER BY rcept_no DESC LIMIT 1
    """), {"c": corp, "y": fy, "p": period}).scalar()


def _periods(session, corp: str, year_min: int):
    """Distinct (fiscal_year, fiscal_period) this corp has report_lines for."""
    rows = session.execute(text("""
        SELECT DISTINCT report_fiscal_year, report_fiscal_period
        FROM report_lines
        WHERE corp_code=:c AND report_fiscal_year >= :ym
        ORDER BY 1, 2
    """), {"c": corp, "ym": year_min}).fetchall()
    return [(int(r[0]), r[1]) for r in rows]


def build_corp(session, corp: str, year_min: int = 2015,
               bases=("consolidated", "separate")) -> int:
    """Build std_v3 rows for one corp. Returns number of rows written."""
    n = 0
    for fy, period in _periods(session, corp, year_min):
        # build the (basis-independent) delta-patch merge + source filings ONCE per period,
        # reuse across both bases (halves report_lines queries in the full build).
        merged = build_merged_lines(session, corp, fy, period)
        if not merged:
            continue
        src = select_canonical_rcepts(session, corp, fy, period)
        for basis in bases:
            col, conflicts, prov = combine_full(session, corp, fy, period, basis,
                                                merged=merged)
            if not col:
                continue  # nothing assembled for this basis (missing / other-basis only)
            if basis == "separate":
                # Separate financial statements have no non-controlling interest —
                # controlling_ni is always net_income by accounting definition, so
                # force it regardless of whether it's NULL or mis-mapped (e.g. a
                # capital-line 'owners' equity' value). Ported from v2's
                # fin2/standardize/rules.py::rule_controlling_ni_fill.
                ni = col.get("net_income")
                if ni is not None and col.get("controlling_ni") != ni:
                    col["controlling_ni"] = ni
            session.execute(
                delete(StdFinancialV3).where(
                    StdFinancialV3.corp_code == corp,
                    StdFinancialV3.fiscal_year == fy,
                    StdFinancialV3.fiscal_period == period,
                    StdFinancialV3.statement_type == basis,
                )
            )
            row = StdFinancialV3(
                corp_code=corp, fiscal_year=fy, fiscal_period=period,
                statement_type=basis,
                source_rcepts=src or None,
                amended_cols=prov["amended_cols"] or None,
                amend_chain=prov["amend_chain"] or None,
                basis_fallback=prov["basis_fallback"],
                conflicts={k: [c["value"] for c in v] for k, v in conflicts.items()} or None,
                industry_lines=prov.get("industry_lines"),
            )
            for c in _VALUE_COLS:
                if c in col:
                    setattr(row, c, col[c])
            # data_quality/period_end (Phase 1, 2026-08-09): ported from std_v2's
            # standardize_corp — see docs/plans/std_v3_dq_shares_period_backfill_plan_2026-08-09.md §3.1/3.2.
            dq = validate_equations(col)
            if period == "FY":
                dq = max(dq, _dq_cross_year_v3(session, corp, basis, col))
            period_end = _period_end(session, corp, fy, period,
                                     src.get("BS") or src.get("IS") or src.get("CF") if src else None)
            dq = _future_guard(dq, period_end)
            row.data_quality = dq
            row.period_end = period_end
            row.shares_out = _select_shares_out(session, corp, fy, period, src)
            session.add(row)
            n += 1

            # extended_financials v3 (2026-09-01, docs/plans/extended_financials_v3_
            # label_based_design_2026-09-01.md §3-2/3-3): DIRECT_MAP 밖 확장 캐노니컬
            # (combine_full()이 이미 계산해 prov["extended"]로 노출) 을 나란히 upsert.
            # StdFinancialV3 와 같은 (corp,fy,period,basis) delete-then-insert 단위.
            session.execute(
                delete(ExtendedFactV3).where(
                    ExtendedFactV3.corp_code == corp,
                    ExtendedFactV3.fiscal_year == fy,
                    ExtendedFactV3.fiscal_period == period,
                    ExtendedFactV3.statement_type == basis,
                )
            )
            for canon, value in prov.get("extended", {}).items():
                session.add(ExtendedFactV3(
                    corp_code=corp, fiscal_year=fy, fiscal_period=period,
                    statement_type=basis, canonical_account=canon, amount_won=value,
                ))
    return n
