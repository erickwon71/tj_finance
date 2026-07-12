"""
확장 재무항목 카탈로그(EXTENDED_CATALOG) — Phase 1 (PRD 12).

`METRIC_REGISTRY`(46종 큐레이트 지표)에 없는 재무제표 항목들. concept_map/account_mapper 가
매핑하지만 std_financials_v2 wide 컬럼으로 승격되지 않은 캐노니컬 계정을, `extended_financials`
뷰(collector/db.py 마이그레이션 `2026_07_extended_financials_view`)를 통해 노출한다.

목록은 실제 DB(`extended_financials` 뷰 DISTINCT canonical_account)를 2026-07-12 스냅샷한 뒤,
`fin2/standardize/rules.py`의 DIRECT_MAP·합산규칙(_CAPEX_CANON 등) 소비분을 제외해 수기 산출.
concept_map.py 확장 시 새 캐노니컬이 여기 없으면 차트빌더에 노출되지 않을 뿐(에러 아님) — 이
파일에 항목을 추가해야 노출된다.

- source="ext_column": extended_financials.canonical_account 를 metric_id 로 그대로 사용.
- v1 은 연간(FY)만 지원(H1/Q3 는 누적 as-filed 라 이산화 미구현) — app/compute/sources.py 에서 가드.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.registry.units import Category, UnitType


@dataclass(frozen=True)
class ExtSpec:
    id: str          # canonical_account (예: "bs.goodwill") — metric_id 로 그대로 사용
    name_ko: str
    unit: UnitType = UnitType.AMOUNT_EOK
    statement: str = ""  # BS/IS/CF (표시용, canonical prefix 에서 자동 유도)


def _spec(canonical: str, name_ko: str, unit: UnitType = UnitType.AMOUNT_EOK) -> ExtSpec:
    stmt = {"bs": "BS", "is": "IS", "cf": "CF"}.get(canonical.split(".", 1)[0], "")
    return ExtSpec(id=canonical, name_ko=name_ko, unit=unit, statement=stmt)


EXTENDED_CATALOG: list[ExtSpec] = [
    # ── 재무상태표(BS) ──
    _spec("bs.accumulated_depreciation", "감가상각누계액"),
    _spec("bs.advance_received", "선수금"),
    _spec("bs.assets_held_for_sale", "매각예정자산"),
    _spec("bs.available_for_sale", "매도가능금융자산"),
    _spec("bs.bond", "사채"),
    _spec("bs.bonds", "사채(비유동)"),
    _spec("bs.capital_surplus", "자본잉여금"),
    _spec("bs.contract_assets", "계약자산"),
    _spec("bs.contract_liabilities", "계약부채"),
    _spec("bs.current_bond", "유동성사채"),
    _spec("bs.current_bonds", "유동성사채(전환사채 등)"),
    _spec("bs.current_lt_debt", "유동성장기차입금"),
    _spec("bs.current_portion_lt_debt", "유동성장기부채"),
    _spec("bs.current_tax_asset", "당기법인세자산"),
    _spec("bs.current_tax_liability", "당기법인세부채"),
    _spec("bs.deferred_tax_asset", "이연법인세자산"),
    _spec("bs.deferred_tax_liability", "이연법인세부채"),
    _spec("bs.derivative_assets", "파생상품자산"),
    _spec("bs.derivative_liabilities", "파생상품부채"),
    _spec("bs.equity_method_investment", "지분법적용투자주식"),
    _spec("bs.fvtpl", "당기손익-공정가치측정금융자산"),
    _spec("bs.goodwill", "영업권"),
    _spec("bs.inventory_detail", "재고자산 상세"),
    _spec("bs.investment_property", "투자부동산"),
    _spec("bs.investments_in_subsidiaries", "종속기업투자주식"),
    _spec("bs.lease_liability", "리스부채"),
    _spec("bs.long_term_investment", "장기금융상품"),
    _spec("bs.net_defined_benefit_asset", "순확정급여자산"),
    _spec("bs.noncontrolling_interest", "비지배지분(자본)"),
    _spec("bs.noncurrent_assets", "비유동자산"),
    _spec("bs.noncurrent_liabilities", "비유동부채"),
    _spec("bs.other_current_assets", "기타유동자산"),
    _spec("bs.other_current_payables", "기타유동부채"),
    _spec("bs.other_equity", "기타자본구성요소"),
    _spec("bs.other_noncurrent_assets", "기타비유동자산"),
    _spec("bs.other_noncurrent_liabilities", "기타비유동부채"),
    _spec("bs.other_receivables", "기타수취채권"),
    _spec("bs.paid_in_capital", "자본금"),
    _spec("bs.pension_liability", "퇴직급여충당부채"),
    _spec("bs.ppe_detail", "유형자산 상세"),
    _spec("bs.prepaid_expenses", "선급비용"),
    _spec("bs.right_of_use_asset", "사용권자산"),
    _spec("bs.short_term_investment", "단기금융상품"),
    _spec("bs.treasury_stock", "자기주식"),

    # ── 현금흐름표(CF) ──
    _spec("cf.acquisition_of_associates", "관계기업투자주식 취득"),
    _spec("cf.acquisition_of_subsidiaries", "종속기업 취득"),
    _spec("cf.available_for_sale_net", "매도가능금융자산 순증감"),
    _spec("cf.beginning_cash", "기초현금"),
    _spec("cf.bond_proceeds", "사채발행"),
    _spec("cf.bond_repaid", "사채상환"),
    _spec("cf.borrowings_proceeds", "차입금 차입"),
    _spec("cf.borrowings_repaid", "차입금 상환"),
    _spec("cf.deposits_change", "예적금 증감"),
    _spec("cf.derivative_adjustments", "파생상품 조정"),
    _spec("cf.dividends_received", "배당금 수취"),
    _spec("cf.ending_cash", "기말현금"),
    _spec("cf.equity_issuance", "유상증자"),
    _spec("cf.fx_effect_on_cash", "환율변동효과"),
    _spec("cf.govt_grant", "정부보조금"),
    _spec("cf.interest_paid", "이자지급"),
    _spec("cf.interest_received", "이자수취"),
    _spec("cf.investment_property_proceeds", "투자부동산 처분"),
    _spec("cf.lease_receivable_proceeds", "리스채권 회수"),
    _spec("cf.lease_repaid", "리스부채 상환"),
    _spec("cf.long_term_loans_change", "장기대여금 증감"),
    _spec("cf.net_change_in_cash", "현금 순증감"),
    _spec("cf.net_income_cf", "당기순이익(CF 기준선)"),
    _spec("cf.noncash_items_subtotal", "비현금항목 조정 소계"),
    _spec("cf.noncash_revenue_deduction", "비현금수익 차감"),
    _spec("cf.operating_pre_adj", "영업활동 조정전 이익"),
    _spec("cf.ppe_proceeds", "유형자산 처분"),
    _spec("cf.ppe_proceeds_detail", "유형자산 처분 상세"),
    _spec("cf.retirement_pay", "퇴직금 지급"),
    _spec("cf.short_term_investment_net", "단기금융상품 순증감"),
    _spec("cf.short_term_loans_change", "단기대여금 증감"),
    _spec("cf.tax_paid", "법인세 납부"),
    _spec("cf.treasury_stock_purchase", "자기주식 취득"),

    # ── 손익계산서(IS) ──
    _spec("is.credit_loss_expense", "대손상각비"),
    _spec("is.eps_basic", "기본주당이익", UnitType.WON_PER_SHARE),
    _spec("is.eps_diluted", "희석주당이익", UnitType.WON_PER_SHARE),
    _spec("is.equity_method_income", "지분법손익"),
    _spec("is.extraordinary_expense", "특별손실"),
    _spec("is.extraordinary_income", "특별이익"),
    _spec("is.finance_income", "금융수익"),
    _spec("is.insurance_revenue", "보험수익"),
    _spec("is.interest_revenue", "이자수익"),
    _spec("is.noncontrolling_ni", "비지배지분 순이익"),
    _spec("is.oci", "기타포괄손익"),
    _spec("is.operating_revenue_ins", "보험영업수익"),
    _spec("is.ordinary_income", "경상이익"),
    _spec("is.other_expense", "기타비용"),
    _spec("is.other_income", "기타수익"),
    _spec("is.sga_detail", "판관비 상세"),
    _spec("is.total_comprehensive_income", "총포괄손익"),
]

EXTENDED_BY_ID: dict[str, ExtSpec] = {s.id: s for s in EXTENDED_CATALOG}
