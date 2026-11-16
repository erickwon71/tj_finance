"""R319 - a basis whose balance sheet is 0 in every row has not filled the statements in: their all-zero tables are dropped."""
from fin2.layer3 import combine


def _lines(statement, basis, values):
    return [{"statement": statement, "basis": basis, "table_seq": 0, "source_rcept": "r", "value_won": v,
             "label_raw": f"row{i}"} for i, v in enumerate(values)]


def test_all_zero_balance_sheet_drops_the_all_zero_statements_of_the_basis(monkeypatch):
    # 00442455 2026Q1: the XBRL current period column is 0 in every row
    lines = (_lines("BS", "consolidated", [0] * 31) + _lines("IS", "consolidated", [0] * 25)
             + _lines("CF", "consolidated", [0] * 19) + _lines("BS", "separate", [5] * 10))
    out = combine._drop_unfilled_statements(lines)
    assert {(r["statement"], r["basis"]) for r in out} == {("BS", "separate")}


def test_all_zero_income_statement_with_a_filled_balance_sheet_is_kept():
    lines = _lines("BS", "consolidated", [7] * 12) + _lines("IS", "consolidated", [0] * 12)
    assert len(combine._drop_unfilled_statements(lines)) == 24


def test_statement_with_one_value_is_kept():
    lines = _lines("BS", "consolidated", [0] * 11 + [3]) + _lines("IS", "consolidated", [0] * 12)
    assert len(combine._drop_unfilled_statements(lines)) == 24


def test_short_all_zero_balance_sheet_is_kept():
    lines = _lines("BS", "consolidated", [0] * 5)
    assert combine._drop_unfilled_statements(lines) == lines


