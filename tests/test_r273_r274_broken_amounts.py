"""R273 damaged comma grouping -> unreadable cell; R274 stacked per-share heading row."""
import parser.xml.dart_xml_parser as dxp
import parser.xml.table_extractor as te


def test_r273_damaged_amount_shapes_are_unreadable():
    for cell in ["10,921,090,50", "2,014,857,92", "(11592,467,385)", "1,879,674,", "1,933146", "2633,407"]:
        assert te._is_broken_comma_grouping(cell), cell
    assert te.unresolved_dot_cell_indices(["10,921,090,50", "5,725,490,326"], "금융수익") == [0]


def test_r273_valid_and_ambiguous_cells_are_untouched():
    for cell in ["322,960,708", "(1,234)", "-11,592,467,385", "1,234.5", "15,32", "5,0", "930,00", "12,5"]:
        assert not te._is_broken_comma_grouping(cell), cell


def test_r273_switch_off():
    te._R273_BROKEN_COMMA_GROUPING = False
    try:
        assert te.unresolved_dot_cell_indices(["10,921,090,50"], "금융수익") == []
    finally:
        te._R273_BROKEN_COMMA_GROUPING = True


def test_r274_digit_break_only_in_per_share_rows():
    row = "<TR><TD>주당이익&cr;   기본주당순이익&cr;   희석주당순이익</TD><TD>172&cr;170</TD></TR>".encode()
    assert b"172&#10;170" in dxp._break_stacked_row_digits(row)
    dates = "<TR><TD>전환사채&cr;발행일&cr;만기</TD><TD>2021.05.25&cr;2021.07.01</TD></TR>".encode()
    assert dxp._break_stacked_row_digits(dates) == dates


def test_r274_stacked_heading_row_splits_into_per_share_rows():
    parts = te._split_parallel_stacked_row("주당이익   기본주당순이익   희석주당순이익", ["172\n170", "2\n2"])
    assert parts == [("기본주당순이익", ["172", "2"]), ("희석주당순이익", ["170", "2"])]


def test_r274_wrapped_label_without_per_share_is_not_split():
    assert te._split_parallel_stacked_row(
        "1. 후속적으로 당기손익으로    재분류되는 항목(주석34)    매도가능금융자산평가손익",
        ["1,000\n2,000"]) is None
