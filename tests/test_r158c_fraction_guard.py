"""R158-c - a dotted cell with a 1-2 digit fraction is not restored by the R158 prefix rule when the fraction is all
zeros, or when the row holds a '%' cell."""
from parser.xml import table_extractor as te


def test_all_zero_fraction_is_not_restored_by_the_prefix_rule():
    assert te._repair_dot_grouped_cells(["45,100.00", "451,000,000"], "11월 03일") == ["45,100.00", "451,000,000"]
    assert te._repair_dot_grouped_cells(["4.00", "4,000"], "x") == ["4.00", "4,000"]


def test_all_zero_fraction_with_its_integer_part_in_the_row_is_still_restored_by_r158b():
    assert te._repair_dot_grouped_cells(["125,309,341.0", "125,309,341"], "x") == ["125,309,341", "125,309,341"]


def test_dotted_cell_beside_a_percent_cell_is_not_restored():
    assert te._repair_dot_grouped_cells(["5.2", "15.29%", "520,000,000"], "펀드") == ["5.2", "15.29%", "520,000,000"]


def test_comma_typo_cells_are_still_restored():
    assert te._repair_dot_grouped_cells(["42,549.493", "42,549,493"], "x") == ["42549493", "42,549,493"]
    assert te._repair_dot_grouped_cells(["10,590,556.9", "10,590,556,900"], "x") == ["10590556900", "10,590,556,900"]
    assert te._repair_dot_grouped_cells(["14,409,591.72", "14,409,591,720"], "x") == ["14409591720", "14,409,591,720"]
