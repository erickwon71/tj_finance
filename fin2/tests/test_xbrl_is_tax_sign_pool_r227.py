"""R227 — IS income-tax sign settled by the table's own arithmetic, also when the
continuing-ops profit row is a filer extension concept (not a standard after-tax concept)."""
from __future__ import annotations

from fin2.extract.report_lines_xbrl import ReportLineRow, _settle_is_tax_sign


def _row(local: str, value: int, basis: str = "consolidated", col: int = 0, order: int = 0):
    return ReportLineRow(
        corp_code="00000000", rcept_no="20190101000001", report_fiscal_year=2019,
        report_fiscal_period="H1", statement="IS", basis=basis, label_raw=local,
        col_index=col, context_fiscal_year=2019, period_kind="duration", is_cumulative=True,
        value_won=value, adecimal=None, unit_source="xbrl", source_ref=f"IS_{basis}/{local}",
        context_raw=None, row_order=order,
    )


def _tax_value(lines):
    return next(r.value_won for r in lines if r.source_ref.endswith("/IncomeTaxExpenseContinuingOperations"))


def test_r170d_standard_after_tax_still_flips():
    lines = [_row("ProfitLossBeforeTax", 1000), _row("IncomeTaxExpenseContinuingOperations", -100),
             _row("ProfitLoss", 900)]
    assert _tax_value(_settle_is_tax_sign(lines)) == 100


def test_standard_after_tax_with_expense_positive_untouched():
    lines = [_row("ProfitLossBeforeTax", 1000), _row("IncomeTaxExpenseContinuingOperations", 100),
             _row("ProfitLoss", 900)]
    assert _tax_value(_settle_is_tax_sign(lines)) == 100


def test_extension_after_tax_row_settles_sign_when_profitloss_includes_discontinued():
    # 베노티앤알 20191101000282 consolidated: tax fact +8,422,622 is a benefit (PBT + tax = continuing profit);
    # ProfitLoss 4,188,448,493 includes discontinued ops, so the standard concepts cannot settle it.
    lines = [_row("ProfitLossBeforeTax", 4191042672), _row("IncomeTaxExpenseContinuingOperations", 8422622),
             _row("udf_IS_2019813104934386_StatementOfComprehensiveIncomeAbstract", 4199465294),
             _row("ProfitLoss", 4188448493)]
    assert _tax_value(_settle_is_tax_sign(lines)) == -8422622


def test_extension_row_pool_not_used_when_expense_equation_holds():
    lines = [_row("ProfitLossBeforeTax", 1000), _row("IncomeTaxExpenseContinuingOperations", 100),
             _row("udf_continuing_profit", 900), _row("udf_other", 1100)]
    assert _tax_value(_settle_is_tax_sign(lines)) == 100


def test_nothing_matches_means_untouched():
    lines = [_row("ProfitLossBeforeTax", 1000), _row("IncomeTaxExpenseContinuingOperations", 100),
             _row("udf_unrelated", 777)]
    assert _tax_value(_settle_is_tax_sign(lines)) == 100


def test_pool_is_per_basis_and_column():
    lines = [_row("ProfitLossBeforeTax", 1000), _row("IncomeTaxExpenseContinuingOperations", 100),
             _row("udf_profit", 1100, basis="separate")]
    assert _tax_value(_settle_is_tax_sign(lines)) == 100
