"""R278 space-grouped thousands, R279 doubled amount cell, R280 blank-label body row."""
import parser.common.amount_normalizer as an
import parser.xml.table_extractor as te
from lxml import etree


def test_r278_space_grouped_amount_is_one_number():
    assert an.parse_amount("860 400 551 ") == 860400551
    assert an.parse_amount("12 345 678") == 12345678


def test_r278_two_values_and_short_groups_unchanged():
    assert an.parse_amount("723,570,750 723,570,750") == 723570750
    assert an.parse_amount("1 000") is None
    assert an.parse_amount("2 8 6,763,456,363") == 286763456363


def test_r278_switch_off():
    an._R278_SPACE_THOUSANDS = False
    try:
        assert an.parse_amount("860 400 551") is None
    finally:
        an._R278_SPACE_THOUSANDS = True


def test_r279_doubled_cell_is_unreadable():
    assert te._is_doubled_amount_cell("760,000,000,760,000,000")
    assert te.unresolved_dot_cell_indices(["760,000,000,760,000,000", "5"], "주식선택권") == [0]


def test_r279_real_four_group_amount_is_not_doubled():
    assert not te._is_doubled_amount_cell("123,456,123,456")
    assert not te._is_doubled_amount_cell("760,000,000")


def _table(label_cell):
    rows = [
        f"<TR><TD>{label_cell}</TD><TD>2,160,000,000</TD><TD>-</TD></TR>",
        "<TR><TD>단기금융상품의 감소</TD><TD>1,000</TD><TD>2,000</TD></TR>",
    ]
    return etree.fromstring("<TABLE>" + "".join(rows) + "</TABLE>")


def test_r280_blank_label_row_with_amount_is_kept():
    rows = te.extract_rows(_table("　"), num_cols=2, keep_all_amount_cells=True)
    assert [r.account_name for r in rows] == ["", "단기금융상품의 감소"]
    assert rows[0].amounts[0] == 2160000000


def test_r280_switch_off_and_notes_drop_it():
    te._R280_BLANK_LABEL_ROWS = False
    try:
        rows = te.extract_rows(_table("　"), num_cols=2, keep_all_amount_cells=True)
        assert [r.account_name for r in rows] == ["단기금융상품의 감소"]
    finally:
        te._R280_BLANK_LABEL_ROWS = True
    rows = te.extract_rows(_table("　"), num_cols=2, keep_all_amount_cells=True, keep_header_rows=True)
    assert [r.account_name for r in rows] == ["단기금융상품의 감소"]
