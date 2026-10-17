"""R251 - a `3개월 | 누적` sub-header printed as the first TBODY row under a period-only THEAD belongs to the header.

삼성카드 20161114002044 (2016Q3) separate IS: 21 rows with two values were dropped as ambiguous.
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

from parser.xml.table_extractor import parse_header_columns

RAW = glob.glob(str(Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI" / "00126292_삼성카드" / "quarter" / "2016" / "20161114002044.xml"))


def _table(tbody_first_label):
    return etree.fromstring(
        "<TABLE><THEAD><TR><TH>과목</TH><TH>주석</TH><TH COLSPAN='2'>제34(당)기 3분기</TH>"
        "<TH COLSPAN='2'>제33(전)기 3분기</TH></TR></THEAD><TBODY>"
        f"<TR><TD>{tbody_first_label}</TD><TD></TD><TD>3개월</TD><TD>누적</TD><TD>3개월</TD><TD>누적</TD></TR>"
        "<TR><TD>매출</TD><TD></TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD></TR></TBODY></TABLE>")


def test_subheader_row_gives_subtypes():
    cols = parse_header_columns(_table(""))
    assert [c.subtype for c in cols if not c.is_note] == ["three_month", "cumulative", "three_month", "cumulative"]


def test_labelled_first_row_is_not_header():
    cols = parse_header_columns(_table("합계"))
    assert [c.subtype for c in cols if not c.is_note] == [None, None, None, None]


@pytest.mark.skipif(not RAW, reason="raw report not available")
def test_samsung_card_separate_is_loaded():
    from fin2.extract.report_lines import extract_report_lines
    lines = extract_report_lines(Path(RAW[0]), rcept_no="20161114002044", corp_code="00126292",
                                 report_fiscal_year=2016, report_fiscal_period="Q3")
    got = {(l.col_index): l.value_won for l in lines
           if l.statement == "IS" and l.basis == "separate" and l.label_raw.startswith("I. 영업수익")}
    assert got == {0: 2507957555452, 1: 2331628947258}
