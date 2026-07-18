"""
XBRL ACODE → canonical 계정 매핑 (fin2 taxonomy).

레거시 `dart_xml_parser._ACODE_TO_STANDARD`(40개) 대체·확장.
canonical 어휘는 텍스트 트랙(account_mapper)과 **동일**한 `bs.x/is.x/cf.x` 네임스페이스 →
fact_v2.canonical_account 가 양 트랙(XBRL/텍스트)에서 일관되게 채워져 R/S 레이어가 통합 가능.

원칙:
  - **명확한 표준 개념만 매핑**. 모호하거나 부호/세부분류가 불확실한 ACODE 는 매핑하지 않음
    (map_acode→None). fact_v2 는 미매핑 행도 acode 원문과 함께 보존하므로 손실 없음 →
    이 표를 보강 후 재추출 없이 backfill 가능.
  - SCE 전용 개념(EquityAtBeginningOfPeriod 등)·세부분해는 매핑 제외(extra_dims/is_dimensional 로 이미 합계제외).

ifrs-full_* = IFRS 표준 택소노미, dart_* = DART 확장. 둘 다 동일 canonical 로 수렴.
"""
from __future__ import annotations

# ── 재무상태표 (BS, instant) ────────────────────────────────────────────
_BS: dict[str, str] = {
    # 자산
    "ifrs-full_Assets": "bs.total_assets",
    "ifrs-full_CurrentAssets": "bs.current_assets",
    "ifrs-full_NoncurrentAssets": "bs.noncurrent_assets",
    "ifrs-full_CashAndCashEquivalents": "bs.cash",
    "ifrs-full_CurrentFinancialAssets": "bs.short_term_investment",
    "ifrs-full_OtherCurrentFinancialAssets": "bs.short_term_investment",
    "ifrs-full_OtherNoncurrentFinancialAssets": "bs.long_term_investment",
    "ifrs-full_NoncurrentFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome": "bs.long_term_investment",
    "ifrs-full_TradeAndOtherCurrentReceivables": "bs.trade_receivables",
    "dart_ShortTermTradeReceivable": "bs.trade_receivables",
    "ifrs-full_Inventories": "bs.inventory",
    "ifrs-full_PropertyPlantAndEquipment": "bs.ppe",
    "ifrs-full_RightofuseAssets": "bs.right_of_use_asset",
    "ifrs-full_RightOfUseAssets": "bs.right_of_use_asset",
    "ifrs-full_IntangibleAssetsOtherThanGoodwill": "bs.intangibles",
    "ifrs-full_Goodwill": "bs.goodwill",
    "ifrs-full_InvestmentProperty": "bs.investment_property",
    "ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates": "bs.investments_in_subsidiaries",
    "ifrs-full_DeferredTaxAssets": "bs.deferred_tax_asset",
    "ifrs-full_OtherCurrentAssets": "bs.other_current_assets",
    "ifrs-full_OtherNoncurrentAssets": "bs.other_noncurrent_assets",
    # 부채
    "ifrs-full_Liabilities": "bs.total_liabilities",
    "ifrs-full_CurrentLiabilities": "bs.current_liabilities",
    "ifrs-full_NoncurrentLiabilities": "bs.noncurrent_liabilities",
    "ifrs-full_ShorttermBorrowings": "bs.short_term_debt",
    "ifrs-full_CurrentBorrowings": "bs.short_term_debt",
    "dart_ShortTermBorrowings": "bs.short_term_debt",
    # 단기 차입성부채 세부(유동성장기부채·유동성사채) → rule_additive_debt 가 단기차입금에 합산.
    # ※ 깨끗한 leaf 개념만(롤업 CurrentBorrowingsAndCurrentPortion… 등은 이중계상 위험으로 제외).
    "ifrs-full_CurrentPortionOfLongtermBorrowings": "bs.current_lt_debt",
    # 사채유동분 + 전환사채유동분 = 서로 다른 상품 → 별도 canonical, rule_additive_debt 가 합산
    # (구: 둘 다 bs.current_bonds 로 collapse → 값충돌 317 보류 → short_term_debt 과소).
    "dart_CurrentPortionOfBonds": "bs.current_bonds_plain",
    "dart_CurrentPortionOfConvertibleBonds": "bs.current_bonds_conv",
    "ifrs-full_NoncurrentBorrowings": "bs.long_term_debt",
    "dart_LongTermBorrowingsGross": "bs.long_term_debt",
    "ifrs-full_LongtermBorrowings": "bs.long_term_debt",
    # 사채(비유동) → rule_additive_debt 가 장기차입금에 합산. 비유동 명시 개념만(총 BondsIssued 제외).
    "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued": "bs.bonds",
    # 리스부채: 유동+비유동은 **서로 다른 항목** → 별도 canonical 로 두고 rule_additive_lease 가
    # lease_liability 로 합산(구: 둘 다 bs.lease_liability 로 collapse → 값충돌 17,895 보류).
    "ifrs-full_CurrentLeaseLiabilities": "bs.lease_current",
    "ifrs-full_NoncurrentLeaseLiabilities": "bs.lease_noncurrent",
    "ifrs-full_TradeAndOtherCurrentPayables": "bs.trade_payables",
    "dart_ShortTermTradePayables": "bs.trade_payables",
    "ifrs-full_OtherCurrentLiabilities": "bs.other_current_payables",
    "ifrs-full_OtherNoncurrentLiabilities": "bs.other_noncurrent_liabilities",
    "ifrs-full_DeferredTaxLiabilities": "bs.deferred_tax_liability",
    "dart_PostemploymentBenefitObligations": "bs.pension_liability",
    # 자본
    "ifrs-full_Equity": "bs.total_equity",
    "ifrs-full_EquityAttributableToOwnersOfParent": "bs.controlling_equity",
    "ifrs-full_NoncontrollingInterests": "bs.noncontrolling_interest",
    "ifrs-full_IssuedCapital": "bs.paid_in_capital",
    "dart_CapitalSurplus": "bs.capital_surplus",
    "ifrs-full_RetainedEarnings": "bs.retained_earnings",
    "ifrs-full_TreasuryShares": "bs.treasury_stock",
    "dart_ElementsOfOtherStockholdersEquity": "bs.other_equity",
}

# ── 손익계산서 (IS, duration) ──────────────────────────────────────────
_IS: dict[str, str] = {
    "ifrs-full_Revenue": "is.revenue",
    "ifrs-full_CostOfSales": "is.cogs",
    "ifrs-full_GrossProfit": "is.gross_profit",
    # 금융(보험) 매출 보조 — 제조업 표준 ifrs-full_Revenue 가 없을 때 rule_revenue_fallback 이
    # '보험 주력' 기업에 한해 매출로 사용(은행/혼합지주 이자우위는 미적용=오값 방지).
    "ifrs-full_InsuranceRevenue": "is.insurance_revenue",
    "dart_OperatingIncomeInsurance": "is.operating_revenue_ins",
    "ifrs-full_RevenueFromInterest": "is.interest_revenue",
    "ifrs-full_InterestRevenueCalculatedUsingEffectiveInterestMethod": "is.interest_revenue",
    "dart_TotalSellingGeneralAdministrativeExpenses": "is.sga",
    # R&D: face IS 에 표준개념으로 태깅한 기업(~327사)만 포착. 대다수는 비용의 성격별
    # 분류 주석에만 있어 별도 note 파서 필요(후속). rd_expense 는 정보컬럼(IS 항등식 무관).
    "ifrs-full_ResearchAndDevelopmentExpense": "is.rd_expense",
    "dart_OperatingIncomeLoss": "is.operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "is.operating_income",
    "ifrs-full_FinanceIncome": "is.finance_income",
    "ifrs-full_FinanceCosts": "is.finance_cost",
    "dart_OtherGains": "is.other_income",
    "dart_OtherLosses": "is.other_expense",
    "ifrs-full_ProfitLossBeforeTax": "is.ebt",
    "ifrs-full_IncomeTaxExpenseContinuingOperations": "is.tax_expense",
    "ifrs-full_ProfitLoss": "is.net_income",
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": "is.controlling_ni",
    "ifrs-full_ProfitLossAttributableToNoncontrollingInterests": "is.noncontrolling_ni",
    "ifrs-full_BasicEarningsLossPerShare": "is.eps_basic",
    "ifrs-full_DilutedEarningsLossPerShare": "is.eps_diluted",
    "ifrs-full_ComprehensiveIncome": "is.total_comprehensive_income",
    "ifrs-full_OtherComprehensiveIncome": "is.oci",
}

# ── 현금흐름표 (CF, duration) ──────────────────────────────────────────
_CF: dict[str, str] = {
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "cf.operating",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "cf.investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "cf.financing",
    "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "cf.capex",
    "ifrs-full_PurchaseOfPropertyPlantAndEquipment": "cf.capex",
    "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": "cf.capex_intangible",
    "ifrs-full_AcquisitionOfIntangibleAssets": "cf.capex_intangible",
    "ifrs-full_ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "cf.ppe_proceeds",
    # ★ A(2026-07-18): bare ifrs-full_DividendsPaid 는 **자본변동표(SCE) 개념**(발생주의 분배액,
    # 현 scope 밖) → cf.dividends_paid 에서 제거. 현금흐름표 값은 …ClassifiedAs…Activities 만.
    # (구: bare 도 매핑 → SCE 값이 CF 값과 collapse, 값충돌 3,019. 참고 dart_xml_parser.py:377.)
    "ifrs-full_DividendsPaidClassifiedAsFinancingActivities": "cf.dividends_paid",
    "ifrs-full_DividendsPaidClassifiedAsOperatingActivities": "cf.dividends_paid",
    "ifrs-full_DividendsReceivedClassifiedAsOperatingActivities": "cf.dividends_received",
    "ifrs-full_InterestPaidClassifiedAsOperatingActivities": "cf.interest_paid",
    "ifrs-full_InterestReceivedClassifiedAsOperatingActivities": "cf.interest_received",
    "ifrs-full_IncomeTaxesPaidRefundClassifiedAsOperatingActivities": "cf.tax_paid",
    "dart_PaymentsOfIncomeTaxesPayable": "cf.tax_paid",
    "ifrs-full_EffectOfExchangeRateChangesOnCashAndCashEquivalents": "cf.fx_effect_on_cash",
    "dart_CashAndCashEquivalentsAtBeginningOfPeriodCf": "cf.beginning_cash",
    "dart_CashAndCashEquivalentsAtEndOfPeriodCf": "cf.ending_cash",
    # 차입 유입/상환: 단기+장기는 서로 다른 흐름 → 별도 canonical, rule_additive_borrowings 가
    # 합산(구: 각각 한 canonical 로 collapse → 값충돌 6,925/5,230 보류).
    "dart_ProceedsFromShortTermBorrowings": "cf.borrow_proceeds_st",
    "dart_ProceedsFromLongTermBorrowings": "cf.borrow_proceeds_lt",
    "dart_RepaymentsOfShortTermBorrowings": "cf.borrow_repaid_st",
    "dart_RepaymentsOfLongTermBorrowings": "cf.borrow_repaid_lt",
    "dart_RepaymentsOfConvertibleBonds": "cf.bond_repaid",
    "dart_AcquisitionOfTreasuryShares": "cf.treasury_stock_purchase",
    "dart_PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities": "cf.lease_repaid",
    "ifrs-full_CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities": "cf.acquisition_of_subsidiaries",
    "dart_PurchaseOfInvestmentsInSubsidiaries": "cf.acquisition_of_subsidiaries",
    "ifrs-full_ProceedsFromGovernmentGrantsClassifiedAsFinancingActivities": "cf.govt_grant",
    "ifrs-full_ProceedsFromGovernmentGrantsClassifiedAsInvestingActivities": "cf.govt_grant",
    "dart_ProceedsFromGovernmentGrantsClassifiedAsFinancingActivities": "cf.govt_grant",
    "dart_ProceedsFromGovernmentGrantsClassifiedAsInvestingActivities": "cf.govt_grant",
    "dart_ProceedsFromSalesOfOtherCurrentFinancialAssets": "cf.short_term_investment_net",
    "dart_PurchaseOfOtherCurrentFinancialAssets": "cf.short_term_investment_net",
}

# 통합 매핑 (충돌 없음 — 각 ACODE 는 단일 canonical)
ACODE_TO_CANONICAL: dict[str, str] = {**_BS, **_IS, **_CF}

# 현 택소노미 버전 식별(감사/재매핑 추적용). DART FORMULA-VERSION 6.x 기준.
TAXONOMY_VERSION = "ifrs-full+dart/2024"


def map_acode(acode: str | None) -> str | None:
    """XBRL ACODE → canonical(bs.x/is.x/cf.x). 미등록은 None(미매핑 보존)."""
    if not acode:
        return None
    return ACODE_TO_CANONICAL.get(acode)
