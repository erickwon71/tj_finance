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

from collector.models import StdFinancialV3
from fin2.layer3.combine import (combine_full, select_canonical_rcepts,
                                 build_merged_lines)

_VALUE_COLS = (
    "total_assets current_assets cash receivables inventory ppe intangibles "
    "total_liabilities current_liabilities short_term_debt long_term_debt "
    "total_equity controlling_equity retained_earnings trade_payables "
    "revenue cogs gross_profit sga rd_expense operating_income interest_expense "
    "ebt tax_expense net_income controlling_ni cfo cfi cff dividends_paid "
    # enrichment (v3-native): combine 이 산출.
    #   · capex/fcf/net_debt            (2026-07-25)
    #   · depreciation/amortization/da_total/ebitda (2026-07-28, 주석 소스 — fin2/layer3/note_da.py)
    # shares_out/data_quality 는 여전히 별도 백필 UPDATE(여기 없음).
    # ★이 목록에 없는 컬럼은 combine 이 값을 내도 **테이블에 안 들어간다**.
    "capex fcf net_debt depreciation amortization da_total ebitda"
).split()


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
            session.add(row)
            n += 1
    return n
