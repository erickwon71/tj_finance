"""machine_note (scope 'note') — printed-amount comparison of the source notes against note_lines
rows, and the conversion of its findings into issue items. No database."""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from fin2.verification import machine_note as mn
from fin2.verification import scope_issues as si

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<TABLE><TR><TD>구분</TD><TD>당기</TD><TD>전기</TD></TR>
<TR><TD>매출채권</TD><TD>1,200,000</TD><TD>(900,000)</TD></TR>
<TR><TD>지분율</TD><TD>50</TD><TD>25</TD></TR>
<TR><TD>기본주당손익</TD><TD>29,191</TD><TD>17,492</TD></TR>
<TR><TD ROWSPAN="2">대여금</TD><TD ROWSPAN="2">5,000</TD><TD>-</TD></TR>
<TR><TD>0</TD></TR></TABLE>
</SECTION-2></SECTION-1>
<SECTION-1><TITLE>II. 사업의 내용</TITLE><TABLE><TR><TD>가</TD><TD>7,777</TD></TR></TABLE></SECTION-1>
</BODY></DOCUMENT>"""


def _src(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    return mn.load_source_tables(str(p))


def _db(values, basis="consolidated", seq=1, labels=("매출채권", "매출채권", "대여금", "대여금")):
    t = mn.DbTable(basis=basis, seq=seq)
    t.labels = frozenset(labels)
    t.amounts = [(v, labels[min(i, len(labels) - 1)], "당기", i, 0) for i, v in enumerate(values)]
    t.values = tuple(values)
    t.valueset = Counter(values)
    return t


def test_source_amounts_skip_small_per_share_and_count_a_merged_cell_once(tmp_path):
    tables, found = _src(tmp_path)
    assert found and len(tables) == 1                       # the 사업의 내용 table is not a note table
    t = tables[0]
    assert t.basis == "consolidated"
    assert t.values == (1200000, -900000, 5000)            # 50 / 25 / 지분율 and 주당손익 not compared
    assert t.alt_values == (1200000, -900000, 5000, 5000)   # merged amount repeated in every cell


def test_equal_lists_are_clean_with_either_merged_reading(tmp_path):
    tables, found = _src(tmp_path)
    assert mn.compare([_db([1200000, -900000, 5000])], tables, found).verdict == "clean"
    assert mn.compare([_db([1200000, -900000, 5000, 5000])], tables, found).verdict == "clean"


def test_value_missing_and_extra_cells(tmp_path):
    tables, found = _src(tmp_path)
    r = mn.compare([_db([1200000, 900000, 5000])], tables, found)           # sign lost
    (f,) = r.findings
    assert (f["kind"], f["db"], f["src"]) == ("value", 900000, -900000)
    assert si.findings_to_items("note", r.findings, "p")[0]["error_type"] == "sign_flip"

    r = mn.compare([_db([1200000, 5000], labels=("매출채권", "대여금"))], tables, found)   # a source amount lost
    assert [(f["kind"], f["src"]) for f in r.findings] == [("missing_cell", -900000)]
    r = mn.compare([_db([1200000, -900000, 5000, 77000])], tables, found)   # an amount the source lacks
    assert [(f["kind"], f["db"]) for f in r.findings] == [("extra_cell", 77000)]


def test_unit_scale_and_unrelated_table(tmp_path):
    tables, found = _src(tmp_path)
    r = mn.compare([_db([1200000, -900000, 5000000])], tables, found)
    assert si.findings_to_items("note", r.findings, "p")[0]["error_type"] == "unit_scale"
    r = mn.compare([_db([1111111, 2222222, 3333333], labels=("전혀", "다른", "표"))], tables, found)
    assert [f["kind"] for f in r.findings] == ["extra_table"]
    assert mn.compare([], [], False).verdict == "no_structure"


def test_note_items_keep_basis_and_number_repeated_keys():
    fs = [{"kind": "extra_cell", "basis": "separate", "table_seq": 4, "db": 9000, "label": "기타",
           "col_label": "당기", "row_order": 2, "col_index": 0}] * 2
    items = si.findings_to_items("note", fs, "p")
    assert [i["basis"] for i in items] == ["separate", "separate"]
    assert [i["account_label"] for i in items] == ["기타", "기타 (#2)"]
    assert all(i["table_ref"] == "4" and i["statement"] == "NOTE" for i in items)


def test_years_are_not_amounts_on_either_side():
    assert mn._read_amount("2015") is None and mn._read_amount(" 2024 ") is None
    assert mn._read_amount("2,015") is None               # mn8: symmetric with the DB side
    assert mn._read_amount("1,950,000") == 1950000 and mn._read_amount("3000") == 3000
    assert mn._is_year(2016) and mn._is_year(-1999) and not mn._is_year(2101) and not mn._is_year(1899)


def test_db_value_raw_with_a_tail_is_read_by_its_first_amount():
    """mn9: undeclared / non-monetary columns keep the printed text in value_raw (value_won NULL)."""
    assert mn._read_db_raw("258,096,615===========") == 258096615
    assert mn._read_db_raw("(5,813)========") == -5813
    assert mn._read_db_raw("17,572,153USD 8,000,000") == 17572153
    assert mn._read_db_raw("1,345,506") == 1345506                       # plain cells unchanged
    assert mn._read_db_raw("5,000 한화 설명") is None and mn._read_db_raw("1,234,5678") is None
    rows = [SimpleNamespace(basis="separate", table_seq=3, row_order=0, label_raw="합 계", col_index=3,
                            col_label="합 계", value_won=None, adecimal=None,
                            value_raw="258,096,615===========")]
    tab = mn.tables_from_rows(rows)[0]
    assert [a[0] for a in tab.amounts] == [258096615]


def test_db_value_raw_cut_at_64_characters_is_read_by_mn10():
    """mn10: the loader cuts value_raw at 64 characters, which can leave the last tail item half printed."""
    cut = "146,443,815USD 156,291,562VND 255,580,714,435CNY 28,500,000EUR 8"
    assert len(cut) == 64 and mn._read_db_raw(cut) == 146443815
    assert mn._read_db_raw("163,293,260USD 202,376,123VND 300,459,829,623CNY 28,500,000") == 163293260
    short = "5,000 USD 12 한화"                                              # short text: no cut tolerance
    assert mn._read_db_raw(short) is None


def test_source_cell_is_read_like_the_loader_mn11():
    """mn11: the source side reads the first amount of an R294 tail cell and a number split by white space."""
    r = mn._read_source_cell
    assert r("20,792,401(VND 377,357,546,463)") == 20792401 and r("12,410,000JPY 78,000") == 12410000
    assert r("12,553,95\n1") == 12553951 and r("4,244, 863") == 4244863
    assert r("(5,813)\n====") == -5813 and r("1,345,506") == 1345506
    # refused like the loader refuses them (R1 / R6): two real amounts, note numbers, years, Korean tails
    assert r("1,234 5,678") is None and r("4, 27, 30") is None and r("2,015 2,016") is None
    assert r("5,000 한화 설명") is None and r("") is None


def test_digits_split_over_lines_are_joined_before_the_first_line_mn13():
    r = mn._read_source_cell
    assert r("1\n4\n9,810") == 149810 and r("(8\n8,\n488)") == -88488
    assert r("1,000\n2,000") == 1000 and r("1,345,506") == 1345506


def test_source_table_counts_tail_and_split_cells_once(tmp_path):
    xml = XML.replace("<TD>(900,000)</TD>", "<TD>(900,000)</TD><TD>20,000(USD 15)</TD><TD><SPAN>3,333,33</SPAN>\n<SPAN>3</SPAN></TD>")
    p = tmp_path / "m.xml"
    p.write_text(xml, encoding="utf-8")
    tables, found = mn.load_source_tables(str(p))
    assert found and (20000 in tables[0].values) and (3333333 in tables[0].values)


def test_stacked_row_is_read_line_by_line_like_r296_mn12(tmp_path):
    cr = "&cr;"
    label = cr.join(["순이자", "  - 이자비용", "  - 이자수익"])
    xml = XML.replace("<TR><TD>지분율</TD>", f"<TR><TD>{label}</TD><TD>{cr}33,042{cr}(32,186)</TD><TD>{cr}30,248{cr}(27,585)</TD></TR>\n<TR><TD>지분율</TD>")
    p = tmp_path / "s.xml"
    p.write_text(xml, encoding="utf-8")
    tables, _ = mn.load_source_tables(str(p))
    assert {33042, -32186, 30248, -27585} <= set(tables[0].values)
    # unequal line counts are left to the single-line reading (R296 leaves them alone)
    assert mn._stacked_lines(["a&cr;b&cr;c", "1,000&cr;2,000"], "a&cr;b&cr;c") is None
    assert mn._stacked_lines(["a&cr;b", "1,000&cr;2,000"], "a&cr;b") is None            # fewer than 3 lines
    assert mn._stacked_lines(["a&cr;b&cr;c", "x&cr;y&cr;z"], "a&cr;b&cr;c") is None      # no amount on any line


def test_one_trailing_dot_after_thousands_groups_is_read_like_the_loader_mn14():
    r = mn._read_source_cell
    assert r("810,000.") == 810000 and r("27,777,623.") == 27777623
    assert r("1.5") is None and r(".") is None and r("99.") is None


def test_dot_grouped_cell_is_read_when_the_row_prints_the_same_digits_mn15():
    d = {"8490", "109886"}
    assert mn._read_dot_grouped("8.490", d) == 8490 and mn._read_dot_grouped("(109.886)", d) == -109886
    assert mn._read_dot_grouped("2.939,347", {"2939347"}) == 2939347
    assert mn._read_dot_grouped("1.234", d) is None and mn._read_dot_grouped("12.5", {"125"}) is None


def test_minus_inside_brackets_is_read_like_the_loader_mn16():
    r = mn._read_source_cell
    assert r("(-715,525)") == -715525 and r("(-128,612,142)") == -128612142 and r("(-0)") is None


def test_decimal_cell_joins_the_alt_values_as_the_rounded_integer_mn17(tmp_path):
    xml = XML.replace("<TD>(900,000)</TD>", "<TD>(900,000)</TD><TD>1107.80</TD><TD>3,671.17원</TD><TD>12,345.5</TD>")
    p = tmp_path / "m.xml"
    p.write_text(xml, encoding="utf-8")
    tables, found = mn.load_source_tables(str(p))
    assert 12346 in tables[0].alt_values and 12346 not in tables[0].values


def test_number_broken_by_a_line_break_inside_a_cell_is_joined_mn18():
    r = mn._read_source_cell
    assert r("3,252,626,&cr;975") == 3252626975 and r("286,&cr;015,&cr;804") == 286015804
    assert r("1,000&cr;2,000") == 1000 and r("-&cr;3,272,017") is None


def test_table_whose_amounts_are_all_printed_in_the_source_is_no_extra_table_mn19(tmp_path):
    tables, found = _src(tmp_path)
    r = mn.compare([_db([1200000, -900000, 5000]), _db([5000], seq=2, labels=("전혀",))], tables, found)
    assert r.verdict == "clean" and r.counts["by_values"] == 1
    r = mn.compare([_db([1200000, -900000, 5000]), _db([5000, 31337], seq=2, labels=("전혀", "다른"))], tables, found)
    assert [f["kind"] for f in r.findings] == ["extra_table"]


def test_value_difference_with_both_numbers_elsewhere_in_the_filing_is_no_finding_mn20(tmp_path):
    tables, found = _src(tmp_path)
    # 1,200,000 in the source is printed in the DB's second table; 77,000 is printed nowhere in the source
    other = _db([1200000], seq=2, labels=("전혀",))
    r = mn.compare([_db([1200000, 900000, 5000]), other], tables, found)
    assert [f["kind"] for f in r.findings] == ["value"]          # 900,000 is a sign flip of -900,000: kept
    t = mn.DbTable(basis="consolidated", seq=3)
    t.labels = frozenset(["매출채권", "대여금"])
    t.amounts = [(1200000, "매출채권", "당기", 0, 0), (5000, "대여금", "당기", 1, 0), (5000, "대여금", "당기", 2, 0)]
    t.values = (1200000, 5000, 5000)
    t.valueset = Counter(t.values)
    twin = _db([-900000], seq=4, labels=("대여금",))
    r = mn.compare([t, twin], tables, found)
    assert not [f for f in r.findings if f["kind"] == "value"]


def test_per_share_test_reads_the_innermost_label_only_mn21():
    # the outer heading names 주당 for every row; only the innermost label decides (DB side)
    rows = [
        mn.SimpleNamespace(basis="consolidated", table_seq=1, row_order=0, label_raw="기본주당이익 계산>유통주식수 (단위: 주)",
                           col_index=0, col_label="", value_won=None, adecimal=None, value_raw="4,312,142"),
        mn.SimpleNamespace(basis="consolidated", table_seq=1, row_order=1, label_raw="기본주당이익 계산>기본주당이익(손실)",
                           col_index=0, col_label="", value_won=500000, adecimal=0, value_raw=None),
    ]
    (t,) = mn.tables_from_rows(rows)
    assert t.values == (4312142,)


def test_angle_bracket_gt_is_no_label_separator_mn23():
    assert "주당" in mn._innermost_label("배당금  <주당 배당금(액면배당률)>:")
    assert mn._innermost_label("기본주당이익 계산>유통주식수 (단위: 주)") == "유통주식수 (단위: 주)"


def test_row_with_an_empty_label_cell_is_no_source_amount_mn24(tmp_path):
    xml = XML.replace(
        "<TR><TD>지분율</TD>",
        "<TR><TD></TD><TD>신한은행</TD><TD>5,900,000</TD><TD>4,500,000</TD></TR>\n<TR><TD>지분율</TD>")
    p = tmp_path / "n24.xml"
    p.write_text(xml, encoding="utf-8")
    tables, _ = mn.load_source_tables(str(p))
    assert 5900000 not in tables[0].alt_values
    mn._MN24_BLANK_LABEL = False
    try:
        tables, _ = mn.load_source_tables(str(p))
        assert 5900000 in tables[0].alt_values
    finally:
        mn._MN24_BLANK_LABEL = True


def test_amount_stored_in_the_row_label_is_no_missing_cell_mn25():
    src = mn.SrcTable(idx=0, basis="consolidated")
    src.amounts = [(15400000, "2019.01.01~", 0), (15269538, "2019.01.01~", 2), (992519970, "2019.01.01~", 3)]
    src.alt_amounts = list(src.amounts)
    src.values = tuple(a[0] for a in src.amounts)
    src.alt_values = src.values
    src.valueset = Counter(src.values)
    src.labels = frozenset(["2019.01.01~"])
    rows = [SimpleNamespace(basis="consolidated", table_seq=1, row_order=0, col_index=c,
                            label_raw="15,400,000>2019.01.01~ 유통주식수", col_label="", value_won=None,
                            adecimal=None, value_raw=raw)
            for c, raw in ((0, "15,269,538"), (1, "992,519,970"))]
    res = mn.compare(mn.tables_from_rows(rows), [src], True)
    assert not res.findings and res.counts["amount_in_label"] == 1


def test_db_raw_of_a_two_line_cell_with_the_break_joined_is_read_by_its_first_amount_mn28():
    assert mn._read_db_raw("227,478(816)") == 227478
    assert mn._read_db_raw("13,985\n(1,145)") == 13985
    assert mn._read_db_raw("(816)") == -816 or mn._read_db_raw("(816)") is None
