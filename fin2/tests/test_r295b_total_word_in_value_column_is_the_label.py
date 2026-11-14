"""R295-b - a note-table row whose label area is blank but whose value area holds a cell that is only a
total word ('합 계', '소계', '계') was dropped whole (the label of a row came from the label area only):
20xx insurance table `| | | 합 계 | 2,410,650` (the word printed under the '적요' column), the foreign
currency table `| | | 합 계 | 1,386,059 | 합 계 | 1,065,889` (the word under the '외화' column of each pair),
a loan table `| | | 계 | ...`. The word is the label of the row; any other text in the value area (a date) is not.
R294-c: a full-width dollar sign is a tail mark like '$'."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines, split_amount_with_tail


def _rows(tmp_path, body):
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE><P>외화 (단위: 천원)</P>
<TABLE>{body}</TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""
    p = tmp_path / "n.xml"
    p.write_text(xml, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY",
                                 include_notes=True)
    return [l for l in lines if l.statement == "note"]


INSURANCE = """<TR><TD>내역</TD><TD>업체명</TD><TD>적요</TD><TD>원금</TD></TR>
<TR><TD>자동차 보험료</TD><TD>현대해상</TD><TD>2016.04.10</TD><TD>1,195,430</TD></TR>
<TR><TD></TD><TD></TD><TD>2016.04.11</TD><TD>1,215,220</TD></TR>
<TR><TD></TD><TD></TD><TD>합   계</TD><TD>2,410,650</TD></TR>"""

PAIRS = """<TR><TD>내역</TD><TD>통화</TD><TD>외화</TD><TD>원화</TD><TD>외화</TD><TD>원화</TD></TR>
<TR><TD>현금</TD><TD>USD</TD><TD>1,318,757</TD><TD>1,535,957</TD><TD>291,684</TD><TD>341,854</TD></TR>
<TR><TD></TD><TD></TD><TD>합 계</TD><TD>1,386,059</TD><TD>합 계</TD><TD>1,065,889</TD></TR>"""


def test_total_word_in_a_value_column_labels_the_row(tmp_path):
    rows = _rows(tmp_path, INSURANCE)
    total = [l for l in rows if l.label_raw.replace(" ", "") == "합계"]
    assert [l.value_won for l in total] == [2410650000], rows
    assert rows[0].label_raw == "자동차 보험료" and rows[0].value_won == 1195430000


def test_paired_columns_total_row_keeps_both_amounts(tmp_path):
    rows = _rows(tmp_path, PAIRS)
    total = {l.col_index: l.value_won for l in rows if l.label_raw.replace(" ", "") == "합계"}
    assert total == {2: 1386059000, 4: 1065889000}, rows        # the word cells themselves carry no value


def test_a_date_in_the_value_column_is_not_a_label(tmp_path):
    rows = _rows(tmp_path, INSURANCE)
    assert not any("2016.04.11" in (l.label_raw or "") for l in rows)
    assert not any(l.value_won == 1215220000 for l in rows)      # the date-only row is still dropped


def test_row_with_a_label_is_unchanged(tmp_path):
    rows = _rows(tmp_path, PAIRS)
    cash = {l.col_index: l.value_won for l in rows if l.label_raw == "현금"}
    assert cash[2] == 1535957000 and cash[4] == 341854000


def test_full_width_dollar_tail_r294c():
    assert split_amount_with_tail("5,000 (＄5,500,000)") == "5,000"
    assert split_amount_with_tail("5,000 ＄500,000") == "5,000"
    assert split_amount_with_tail("5,000 (＄5)") is None
