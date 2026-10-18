"""R258 - blank lines / parenthesized negatives between `&cr;`-stacked amounts keep their line break and
the R152 first token handles a parenthesized negative head.
R259 - a parent heading stacked with its child lines yields the parent total (first token) only when it
equals the sum of the rest.
"""
import glob
from pathlib import Path

import pytest

from parser.xml.dart_xml_parser import sanitize_dart_xml
from parser.xml.table_extractor import (_first_of_compacted_supplementary_cell,
                                        _first_of_stacked_parent_total)

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _s(text: str) -> str:
    return sanitize_dart_xml(text.encode()).decode()


def test_blank_lines_between_stacked_amounts_keep_a_break():
    assert _s("<TD>53,040,262,118&cr;&cr;43,714,275,259&cr;30,762,805,127</TD>").split("&#10;") == [
        "<TD>53,040,262,118", "43,714,275,259", "30,762,805,127</TD>"]


def test_lone_dash_line_and_parenthesized_negative_line_keep_a_break():
    assert _s("<TD>2,259,202&cr;-&cr;176,623&cr;2,082,579</TD>").count("&#10;") == 3
    assert "&#10;" in _s("<TD>190,809&cr;(3,162)</TD>")


def test_footnote_marker_is_not_turned_into_a_break():
    assert "&#10;" not in _s("<TD>1,234&cr;(1)</TD>")


def test_parenthesized_negative_head_is_the_first_token():
    assert _first_of_compacted_supplementary_cell("(129,411,450)(341,071,045)") == "(129,411,450)"
    assert _first_of_compacted_supplementary_cell("(68,276,375)\n26,156,905") == "(68,276,375)"


def test_stacked_parent_total_requires_the_sum_proof():
    assert _first_of_stacked_parent_total("3,762,471\n65,393\n3,697,078") == "3,762,471"
    assert _first_of_stacked_parent_total("2,259,202\n-\n176,623\n2,082,579") == "2,259,202"
    assert _first_of_stacked_parent_total("1,012,264\n821,771\n190,809(316)") == "1,012,264"
    assert _first_of_stacked_parent_total("5,000\n1,000\n2,000") == "5,000\n1,000\n2,000"   # no proof
    assert _first_of_stacked_parent_total("3,762,471") == "3,762,471"


def _lines(rcept, corp, fy, fp):
    from fin2.extract.report_lines import extract_report_lines
    g = glob.glob(str(ROOT / "*" / "*" / "*" / "*" / f"{rcept}.xml"))
    if not g:
        pytest.skip("raw report not available")
    return extract_report_lines(Path(g[0]), rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                report_fiscal_period=fp, include_notes=False)


def test_korea_re_net_income_row_is_loaded():
    got = {l.value_won for l in _lines("20180515001565", "00113191", 2018, "Q1")
           if l.statement == "IS" and l.basis == "separate" and l.col_index == 0 and "순이익" in l.label_raw}
    assert 53040262118 in got


def test_daishin_oci_parent_rows_are_loaded():
    got = {l.value_won for l in _lines("20190814001026", "00110893", 2019, "H1")
           if l.statement == "IS" and l.basis == "consolidated" and l.col_index == 0 and "후속적으로" in l.label_raw}
    assert {7896615000, 9116726000} <= got
