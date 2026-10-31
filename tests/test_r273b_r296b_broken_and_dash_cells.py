"""R273-b - more damaged comma groupings are unreadable cells (NULL + value_raw), two-group shapes stay readable.
R296-b - a cell whose first line is a lone dash followed by an amount line is two stacked lines, not a negative.
"""
import pytest

from parser.common.amount_normalizer import parse_amount
from parser.xml.dart_xml_parser import sanitize_dart_xml
from parser.xml.table_extractor import _is_broken_comma_grouping


@pytest.mark.parametrize("cell", [
    "1,1112,007", "99,1111,000", "-,025,543", ",663,413,476", ",5232", "9,999,,999", "(393,,174,541)",
    "(17,08,854)", "99,99,999", "33,94,011", "99,999,99,999", "9,9,99,999",
])
def test_more_damaged_groupings_are_unreadable(cell):
    assert _is_broken_comma_grouping(cell)


@pytest.mark.parametrize("cell", [
    "552,24", "99,99", "(999,9)", "12,345", "(1,234,567)", "4, 27, 30", "27,28,29", "12,5,100", "2015,12,31",
    "1,234.5", "10,20", "1,5",
])
def test_readable_or_ambiguous_shapes_are_left_alone(cell):
    assert not _is_broken_comma_grouping(cell)


def test_lone_dash_first_line_breaks_after_the_dash():
    out = sanitize_dart_xml('<TD W="1">-&cr;3,272,017</TD>'.encode()).decode()
    assert out == '<TD W="1">-&#10;3,272,017</TD>'


def test_dash_first_line_is_only_a_cell_start_dash():
    # a minus glued to the previous text, and an amount without a thousands group, keep the old reading
    assert "&#10;" not in sanitize_dart_xml("<TD>가-&cr;3,272,017</TD>".encode()).decode()
    assert "&#10;" not in sanitize_dart_xml("<TD>-&cr;327</TD>".encode()).decode()


def test_two_line_dash_then_amount_cell_is_unreadable_not_negative():
    assert parse_amount("-\n3,272,017", 1) is None
    assert parse_amount("-3,272,017", 1) == -3272017
    assert parse_amount("- 3,272,017", 1) == -3272017          # a space is a printed minus sign, not a line
    assert parse_amount("-", 1) is None or parse_amount("-", 1) == 0
