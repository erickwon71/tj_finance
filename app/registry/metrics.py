"""
지표 카탈로그(METRIC_REGISTRY).

각 지표는 MetricSpec 한 줄로 선언 — id·이름·카테고리·단위·source·key.
source 가 기존 엔진/컬럼이면 코드 0(등록만으로 추가). config-driven 확장의 핵심.

- source="column"  : std_v2/calendar 행에서 row[key] 직접 (FINANCIALS, 금액)
- source="ratios"  : analyzer.ratio_engine.compute_ratios(curr, prev) 의 속성 key
                     (PROFIT/GROWTH/STABILITY)

Phase 2 범위 = 기간별(per-period) 계산 가능한 column·ratios 지표.
MULTIPLE/배당/대가(Buffett 등)는 가격·전체시계열 의존이라 후속 Phase 에서 추가.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.registry.units import Category, UnitType


@dataclass(frozen=True)
class MetricSpec:
    id: str
    name_ko: str
    category: Category
    unit: UnitType
    source: str           # "column" | "ratios"
    key: str              # 컬럼명 또는 FinancialRatios 속성명
    needs_prev: bool = False


_C = Category
_U = UnitType

METRIC_REGISTRY: list[MetricSpec] = [
    # ── 재무데이터 (column, 억원) ──
    MetricSpec("revenue", "매출액", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "revenue"),
    MetricSpec("cogs", "매출원가", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "cogs"),
    MetricSpec("gross_profit", "매출총이익", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "gross_profit"),
    MetricSpec("sga", "판관비", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "sga"),
    MetricSpec("rd_expense", "R&D비용", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "rd_expense"),
    MetricSpec("operating_income", "영업이익", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "operating_income"),
    MetricSpec("ebt", "세전이익", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "ebt"),
    MetricSpec("net_income", "순이익", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "net_income"),
    MetricSpec("controlling_ni", "지배주주순이익", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "controlling_ni"),
    MetricSpec("ebitda", "EBITDA", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "ebitda"),
    MetricSpec("total_assets", "자산총계", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "total_assets"),
    MetricSpec("total_liabilities", "부채총계", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "total_liabilities"),
    MetricSpec("total_equity", "자본총계", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "total_equity"),
    MetricSpec("controlling_equity", "지배지분", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "controlling_equity"),
    MetricSpec("cash", "현금", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "cash"),
    MetricSpec("net_debt", "순차입금", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "net_debt"),
    MetricSpec("inventory", "재고자산", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "inventory"),
    MetricSpec("receivables", "매출채권", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "receivables"),
    MetricSpec("cfo", "영업현금흐름", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "cfo"),
    MetricSpec("cfi", "투자현금흐름", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "cfi"),
    MetricSpec("cff", "재무현금흐름", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "cff"),
    MetricSpec("capex", "CAPEX", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "capex"),
    MetricSpec("fcf", "잉여현금흐름", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "fcf"),
    MetricSpec("dividends_paid", "배당금지급", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "dividends_paid"),
    MetricSpec("da_total", "감가상각비", _C.FINANCIALS, _U.AMOUNT_EOK, "column", "da_total"),

    # ── 수익성 (ratios) ──
    MetricSpec("gross_margin", "매출총이익률", _C.PROFIT, _U.PCT, "ratios", "gross_margin"),
    MetricSpec("op_margin", "영업이익률", _C.PROFIT, _U.PCT, "ratios", "op_margin"),
    MetricSpec("net_margin", "순이익률", _C.PROFIT, _U.PCT, "ratios", "net_margin"),
    MetricSpec("ebitda_margin", "EBITDA마진", _C.PROFIT, _U.PCT, "ratios", "ebitda_margin"),
    MetricSpec("roe", "ROE", _C.PROFIT, _U.PCT, "ratios", "roe"),
    MetricSpec("roa", "ROA", _C.PROFIT, _U.PCT, "ratios", "roa"),
    MetricSpec("roic", "ROIC", _C.PROFIT, _U.PCT, "ratios", "roic"),
    MetricSpec("asset_turnover", "자산회전율", _C.PROFIT, _U.MULTIPLE_X, "ratios", "asset_turnover"),
    MetricSpec("effective_tax_rate", "유효세율", _C.PROFIT, _U.PCT, "ratios", "effective_tax_rate"),

    # ── 성장성 (ratios, 전기 필요) ──
    MetricSpec("revenue_growth", "매출성장률", _C.GROWTH, _U.PCT, "ratios", "revenue_growth", True),
    MetricSpec("op_income_growth", "영업이익성장률", _C.GROWTH, _U.PCT, "ratios", "op_income_growth", True),
    MetricSpec("net_income_growth", "순이익성장률", _C.GROWTH, _U.PCT, "ratios", "net_income_growth", True),
    MetricSpec("asset_growth", "자산성장률", _C.GROWTH, _U.PCT, "ratios", "asset_growth", True),

    # ── 안정성 (ratios) ──
    MetricSpec("debt_ratio", "부채비율", _C.STABILITY, _U.PCT, "ratios", "debt_ratio"),
    MetricSpec("current_ratio", "유동비율", _C.STABILITY, _U.PCT, "ratios", "current_ratio"),
    MetricSpec("interest_coverage", "이자보상배율", _C.STABILITY, _U.MULTIPLE_X, "ratios", "interest_coverage"),
    MetricSpec("net_debt_ebitda", "순부채/EBITDA", _C.STABILITY, _U.MULTIPLE_X, "ratios", "net_debt_ebitda"),
    MetricSpec("capex_to_revenue", "CAPEX/매출", _C.STABILITY, _U.PCT, "ratios", "capex_to_revenue"),
    MetricSpec("fcf_to_revenue", "FCF/매출", _C.STABILITY, _U.PCT, "ratios", "fcf_to_revenue"),
    MetricSpec("cfo_to_ni", "CFO/순이익", _C.STABILITY, _U.MULTIPLE_X, "ratios", "cfo_to_ni"),
    MetricSpec("accrual_ratio", "발생액비율", _C.STABILITY, _U.PCT, "ratios", "accrual_ratio"),
    MetricSpec("ccc", "현금전환주기", _C.STABILITY, _U.DAYS, "ratios", "ccc"),
    MetricSpec("dso", "매출채권회전일(DSO)", _C.STABILITY, _U.DAYS, "ratios", "dso"),
    MetricSpec("dio", "재고회전일(DIO)", _C.STABILITY, _U.DAYS, "ratios", "dio"),
    MetricSpec("dpo", "매입채무회전일(DPO)", _C.STABILITY, _U.DAYS, "ratios", "dpo"),
]

REGISTRY_BY_ID: dict[str, MetricSpec] = {m.id: m for m in METRIC_REGISTRY}


def metrics_by_category() -> dict[Category, list[MetricSpec]]:
    out: dict[Category, list[MetricSpec]] = {}
    for m in METRIC_REGISTRY:
        out.setdefault(m.category, []).append(m)
    return out
