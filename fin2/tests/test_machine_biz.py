"""machine_biz (scope 'biz') — grid comparison of the source XML against biz_section_tables rows,
and the conversion of its findings into issue items. Pure functions, no database."""
from __future__ import annotations

from fin2.verification import machine_biz as mb
from fin2.verification import scope_issues as si

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>II. 사업의 내용</TITLE>
<TABLE><TR><TD>부 문</TD><TD>제56기</TD></TR>
<TR><TD>H&amp;B사업본부</TD><TD>1,000</TD></TR>
<TR><TD>TV&cr;모니터</TD><TD>2,000</TD></TR></TABLE>
<TABLE><TR><TD>구분</TD><TD>금액</TD></TR><TR><TD>기타</TD><TD>5</TD></TR></TABLE>
</SECTION-1>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<TABLE><TR><TD>자산</TD><TD>9</TD></TR></TABLE></SECTION-1></BODY></DOCUMENT>"""


def _grids(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(XML, encoding="utf-8")
    return mb.load_source_grids(str(p))


def _db(grid, ord_=0):
    return {"table_ord": ord_, "domain": "sales", "metric": "sales", "grid": grid}


def test_source_grids_and_section_flag(tmp_path):
    grids, found = _grids(tmp_path)
    assert found
    assert [g.in_section for g in grids] == [True, True, False]
    assert grids[0].cells[1] == ["H&B사업본부", "1,000"]
    assert grids[0].cells[2][0] == "TV모니터"            # &cr; dropped, whitespace ignored


def test_equal_grid_is_clean_and_whitespace_insensitive(tmp_path):
    grids, found = _grids(tmp_path)
    res = mb.compare([_db([["부  문", "제56기"], ["H&B 사업본부", "1,000"], ["TV 모니터", "2,000"]])],
                     grids, found)
    assert res.verdict == "clean" and res.counts["exact"] == 1
    assert res.counts["unstored_numeric_tables"] == 1     # the second section table is not stored


def test_dropped_ampersand_is_a_cell_finding(tmp_path):
    grids, found = _grids(tmp_path)
    res = mb.compare([_db([["부 문", "제56기"], ["H사업본부", "1,000"], ["TV모니터", "2,000"]])],
                     grids, found)
    assert res.verdict == "mismatch"
    (f,) = res.findings
    assert (f["kind"], f["db"], f["src"], f["row"], f["col"]) == ("cell", "H사업본부", "H&B사업본부", 1, 0)
    items = si.findings_to_items("biz", res.findings, "[machine mb1]")
    assert items[0]["error_type"] == "label_mismatch"      # same digits, different text
    assert items[0]["table_ref"] == "0" and items[0]["statement"] == "BIZ"


def test_changed_number_is_value_mismatch_and_row_diffs(tmp_path):
    grids, found = _grids(tmp_path)
    # a table sharing < MATCH_MIN of its cells with every source table has no counterpart
    res = mb.compare([_db([["부 문", "제56기"], ["H&B사업본부", "1,001"]])], grids, found)
    assert [f["kind"] for f in res.findings] == ["extra_table"]
    # a missing source row (same cells otherwise) is a row finding
    res = mb.compare([_db([["부 문", "제56기"], ["H&B사업본부", "1,000"]])], grids, found)
    assert [f["kind"] for f in res.findings] == ["row_missing"]
    res2 = mb.compare([_db([["부 문", "제56기"], ["H&B사업본부", "1,001"], ["TV모니터", "2,000"]])],
                      grids, found)
    (f,) = res2.findings
    items = si.findings_to_items("biz", res2.findings, "[machine mb1]")
    assert items[0]["error_type"] == "value_mismatch" and f["col"] == 1


def test_table_without_counterpart_and_no_structure(tmp_path):
    grids, found = _grids(tmp_path)
    res = mb.compare([_db([["전혀", "다른"], ["표", "xyz"]])], grids, found)
    assert [f["kind"] for f in res.findings] == ["extra_table"]
    assert si.findings_to_items("biz", res.findings, "p")[0]["error_type"] == "extra_table"
    assert mb.compare([], [], False).verdict == "no_structure"


def test_repeated_label_gets_a_numbered_key():
    findings = [
        {"kind": "cell", "table_ord": 3, "row": 1, "col": 0, "label": "L", "header": "h", "db": "a", "src": "b"},
        {"kind": "cell", "table_ord": 3, "row": 1, "col": 0, "label": "L", "header": "h", "db": "c", "src": "d"},
    ]
    items = si.findings_to_items("biz", findings, "p")
    assert [i["account_label"] for i in items] == ["L", "L (#2)"]
    only_second = si.findings_to_items("biz", findings, "p", select=[2])
    assert [i["account_label"] for i in only_second] == ["L (#2)"]


def test_empty_cells_are_not_a_difference(tmp_path):
    grids, found = _grids(tmp_path)
    res = mb.compare([_db([["", "부 문", "", "제56기"], ["H&B사업본부", "", "1,000"],
                           ["TV모니터", "2,000"]])], grids, found)
    assert res.verdict == "clean" and res.counts["empty_shape"] == 1


def test_identical_grid_wins_over_a_reordered_twin(tmp_path):
    """A correction report holds [정정전] and [정정후] versions of a table: same cells, other order."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>II. 사업의 내용</TITLE>
<TABLE><TR><TD>가</TD><TD>1</TD></TR><TR><TD>나</TD><TD>2</TD></TR><TR><TD>다</TD><TD>3</TD></TR></TABLE>
<TABLE><TR><TD>나</TD><TD>2</TD></TR><TR><TD>다</TD><TD>3</TD></TR><TR><TD>가</TD><TD>1</TD></TR></TABLE>
</SECTION-1></BODY></DOCUMENT>"""
    p = tmp_path / "h.xml"
    p.write_text(xml, encoding="utf-8")
    grids, found = mb.load_source_grids(str(p))
    second = [["나", "2"], ["다", "3"], ["가", "1"]]
    assert mb.compare([_db(second)], grids, found).verdict == "clean"
    # not identical to either: the twin with the closer row order is the counterpart
    res = mb.compare([_db([["나", "2"], ["다", "3"], ["가", "9"]])], grids, found)
    assert [f["src"] for f in res.findings] == ["1"]
