"""주주환원(배당+자기주식) 로더 — dividend_facts/treasury_activity + standard_financials 조인.
파생(배당성향 재계산 폴백·총주주환원율)은 앱측 pandas/dict 계산으로 처리한다(단일 기업
온디맨드 조회라 트리비얼 — 재사용처가 생기면 DB 뷰 승격 검토, Phase 2 PRD §4.5 결정).
UI 비의존.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from analyzer.ratio_engine import load_standard_financials
from collector.db import get_session


def load_dividend_series(corp_code: str, years: int = 15) -> list[dict]:
    """연도별 배당 지표(dps_common/payout_ratio/dividend_yield_common 등). 최신→과거."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT fiscal_year, dps_common, dps_pref, stock_dividend_ratio,
                   total_dividend_amount, payout_ratio, dividend_yield_common
            FROM dividend_facts WHERE corp_code = :c
            ORDER BY fiscal_year DESC LIMIT :n
        """), {"c": corp_code, "n": years}).mappings().fetchall()
    return [dict(r) for r in rows]


def load_dividend_series_for_chart(corp_code: str, basis: str = "consolidated") -> list[dict]:
    """차트빌더용 — period_end 를 std_financials_v2 에서 조인(app.data.extended.load_extended_all
    과 동일 조인 패턴, 동일 (corp,fy,fp,basis) 축 정렬 보장)."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT d.fiscal_year, s.period_end, d.dps_common, d.payout_ratio,
                   d.dividend_yield_common, d.total_dividend_amount
            FROM dividend_facts d
            JOIN std_financials_v2 s
              ON s.corp_code = d.corp_code AND s.fiscal_year = d.fiscal_year
             AND s.fiscal_period = 'FY' AND s.statement_type = :basis
             AND s.version = 1 AND NOT COALESCE(s.is_stub, false)
             AND NOT COALESCE(s.is_discrete, false)
            WHERE d.corp_code = :c
            ORDER BY d.fiscal_year DESC
        """), {"c": corp_code, "basis": basis}).mappings().fetchall()
    return [dict(r) for r in rows]


def load_treasury_activity_detail(corp_code: str, fiscal_year: int) -> list[dict]:
    """해당 연도 취득방법별 상세(총계/소계 subtotal 행 포함, raw 원본 순서 그대로)."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT stock_kind, acqs_method1, acqs_method2, acqs_method3,
                   qty_begin, qty_acquired, qty_disposed, qty_incinerated, qty_end, remark
            FROM treasury_activity WHERE corp_code = :c AND fiscal_year = :y
            ORDER BY id
        """), {"c": corp_code, "y": fiscal_year}).mappings().fetchall()
    return [dict(r) for r in rows]


def _load_treasury_purchase_amount_won(corp_code: str) -> dict[int, int]:
    """Phase 1 extended_financials 의 cf.treasury_stock_purchase(원) — 자기주식 취득 순취득금액
    폴백 소스(treasury_activity 는 수량만 있어 금액환산 불가). CF 관행상 현금유출은 음수로
    저장되므로 절대값으로 변환(취득 규모는 양수로 취급, 총주주환원율 가산용). {fiscal_year: amount_won}."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT fiscal_year, amount_won FROM extended_financials
            WHERE corp_code = :c AND basis = 'consolidated' AND fiscal_period = 'FY'
              AND canonical_account = 'cf.treasury_stock_purchase'
        """), {"c": corp_code}).fetchall()
    return {r[0]: abs(r[1]) for r in rows if r[1] is not None}


def compute_shareholder_return(
    corp_code: str, statement_type: str = "consolidated", years: int = 15,
) -> list[dict]:
    """연도별 배당성향(공시우선+재계산폴백)·총주주환원율. fiscal_year 내림차순.

    - 배당성향 = 공시된 payout_ratio 우선, 없으면 total_dividend_amount / controlling_ni 폴백.
    - 총주주환원율 = (총배당금 + 자사주 순취득금액) / controlling_ni.
    - 자사주 순취득금액 = extended_financials 의 cf.treasury_stock_purchase(원, 현금흐름표
      기준 유출액이라 이미 양수=취득 규모). treasury_activity 는 수량만 있어 금액 산출 불가.
    """
    div_by_fy = {r["fiscal_year"]: r for r in load_dividend_series(corp_code, years)}
    sf_by_fy = {r["fiscal_year"]: r for r in load_standard_financials(corp_code, statement_type, "FY", years)}
    buyback_by_fy = _load_treasury_purchase_amount_won(corp_code)

    out = []
    for fy in sorted(set(div_by_fy) | set(sf_by_fy), reverse=True):
        d = div_by_fy.get(fy, {})
        sf = sf_by_fy.get(fy, {})
        ni: Optional[int] = sf.get("controlling_ni") if sf.get("controlling_ni") is not None else sf.get("net_income")

        total_div_won: Optional[int] = None
        if d.get("total_dividend_amount") is not None:
            total_div_won = d["total_dividend_amount"] * 1_000_000  # 공시 단위=백만원

        payout = d.get("payout_ratio")
        if payout is None and total_div_won is not None and ni:
            payout = total_div_won / ni * 100

        buyback_won = buyback_by_fy.get(fy)
        total_return_won = None
        if total_div_won is not None or buyback_won is not None:
            total_return_won = (total_div_won or 0) + (buyback_won or 0)
        total_return_ratio = (total_return_won / ni * 100) if total_return_won is not None and ni else None

        out.append({
            "fiscal_year": fy,
            "dps_common": d.get("dps_common"),
            "dps_pref": d.get("dps_pref"),
            "dividend_yield_common": d.get("dividend_yield_common"),
            # postgres NUMERIC 산술은 Decimal 을 반환 — pandas/pyarrow 가 float 와 섞인 object
            # 컬럼을 직렬화할 때 실패하므로 여기서 float 로 통일(정밀도 요구 없는 표시값).
            "total_dividend_amount_won": float(total_div_won) if total_div_won is not None else None,
            "payout_ratio": float(payout) if payout is not None else None,
            "buyback_amount_won": float(buyback_won) if buyback_won is not None else None,
            "total_shareholder_return_won": float(total_return_won) if total_return_won is not None else None,
            "total_shareholder_return_ratio": float(total_return_ratio) if total_return_ratio is not None else None,
            "controlling_ni": float(ni) if ni is not None else None,
        })
    return out
