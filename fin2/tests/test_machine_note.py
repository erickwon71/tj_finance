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
