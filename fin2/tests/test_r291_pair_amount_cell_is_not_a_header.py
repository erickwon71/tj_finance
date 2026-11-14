"""R291 - a cell that prints two amounts ('5,805,822 (6,364,923)': a foreign-currency amount and its
won equivalent in parentheses) is neither read by parse_amount nor matched by _NUMBER_PATTERN. The
header boundary of a note table is "the first row with a number-only cell", so the FIRST DATA ROW of
such a table was taken for a header row: its values were lost and its text became part of the column
names ('2016.09.30>5,805,822 (6,364,923)', 20161114001338 separate table 13). Fixed in
_grid_header_split (the row is data) and in _emit_note_lines (the pair cell keeps its row, value NULL,
printed text in value_raw - R290)."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines, is_pair_amount_cell

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>차입금 내역 (단위: 천원)</P>
<TABLE>
<TR><TD>구분</TD><TD>만기일</TD><TD>2016.09.30</TD><TD>2015.12.31</TD></TR>
<TR><TD>산업은행</TD><TD>2016.12.27</TD><TD>5,805,822 (6,364,923)</TD><TD>8,981,745 (10,526,606)</TD></TR>
<TR><TD>시설자금</TD><TD>2016.12.31</TD><TD>5,018,850</TD><TD>5,018,850</TD></TR>
<TR><TD>운영자금</TD><TD>2016.12.31</TD><TD>11,399,000</TD><TD>11,399,000</TD></TR>
</TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _rows(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY",
                                 include_notes=True)
    return [l for l in lines if l.statement == "note"]


def test_pair_amount_cell_detection_is_narrow():
    assert is_pair_amount_cell("5,805,822 (6,364,923)") and is_pair_amount_cell("198,879\n(218,000)")
    assert not is_pair_amount_cell("2016 2015") and not is_pair_amount_cell("1,234 (주1)")
    assert not is_pair_amount_cell("1,234") and not is_pair_amount_cell("12 (3)")


def test_first_data_row_is_data_not_header(tmp_path):
    rows = _rows(tmp_path)
    first = [l for l in rows if l.label_raw.strip().startswith("산업은행")]
    assert first, "the first data row was swallowed by the header"
    raws = {l.value_raw for l in first}
    assert "5,805,822 (6,364,923)" in raws and "8,981,745 (10,526,606)" in raws
    assert all(l.value_won is None for l in first if l.value_raw)           # NULL row, printed text
    # the column names are the real header, not header + the first data row
    labels = {l.col_label for l in rows if l.col_label}
    assert not any("5,805,822" in x for x in labels), labels
    # the other rows are read as before (천원 -> 원)
    assert any(l.value_won == 5018850000 for l in rows) and any(l.value_won == 11399000000 for l in rows)
