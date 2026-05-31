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
    "ifrs-full_NoncurrentBorrowings": "bs.long_term_debt",
    "dart_LongTermBorrowingsGross": "bs.long_term_debt",
    "ifrs-full_CurrentLeaseLiabilities": "bs.lease_liability",
    "ifrs-full_NoncurrentLeaseLiabilities": "bs.lease_liability",
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
    "dart_TotalSellingGeneralAdministrativeExpenses": "is.sga",
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
    "ifrs-full_DividendsPaid": "cf.dividends_paid",
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
    "dart_ProceedsFromShortTermBorrowings": "cf.borrowings_proceeds",
    "dart_ProceedsFromLongTermBorrowings": "cf.borrowings_proceeds",
    "dart_RepaymentsOfShortTermBorrowings": "cf.borrowings_repaid",
    "dart_RepaymentsOfLongTermBorrowings": "cf.borrowings_repaid",
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
