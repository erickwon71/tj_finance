"""R206 — uncertain cells of the 22 R192-excluded filings are loaded as printed (cell list, not a filing switch)."""
from types import SimpleNamespace

from fin2.extract import sce_as_printed as ap

_KEY = ("20240516000677", "consolidated", "Ⅸ.자기주식 거래로 인한 증감", "자본>자본 합계", 8)


def _line(rcept_key=_KEY, value=-115430090, statement="SCE"):
    _, basis, label, col, row = rcept_key
    return SimpleNamespace(statement=statement, basis=basis, label_raw=label, col_label=col, row_order=row, value_won=value)


def test_listed_cell_with_the_r192_value_is_restored_to_the_printed_value():
    ln = _line()
    assert ap.apply_as_printed_cells([ln], "20240516000677") == 1
    assert ln.value_won == 115430090


def test_cell_with_any_other_value_is_left_alone():
    ln = _line(value=777)
    assert ap.apply_as_printed_cells([ln], "20240516000677") == 0
    assert ln.value_won == 777


def test_other_filing_other_statement_and_missing_rcept_are_untouched():
    a, b = _line(), _line(statement="BS")
    assert ap.apply_as_printed_cells([a], "20990101000001") == 0
    assert ap.apply_as_printed_cells([b], "20240516000677") == 0
    assert ap.apply_as_printed_cells([a], "") == 0
    assert a.value_won == -115430090 and b.value_won == -115430090


def test_table_is_a_pure_sign_pair_for_22_filings():
    assert len({k[0] for k in ap._AS_PRINTED_CELLS}) == 22
    assert len(ap._AS_PRINTED_CELLS) == 103
    assert all(r192 == -printed != 0 for r192, printed in ap._AS_PRINTED_CELLS.values())
