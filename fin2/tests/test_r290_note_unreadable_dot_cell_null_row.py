"""R290 - R160 (an unresolved '.' cell keeps its ROW with value_won NULL and the printed text in
value_raw) also holds for the NOTES. The notes' emit loop skipped every cell whose parsed amount
was None, so the foreign-currency amount columns of an 외화 exposure table ('6,193,584.95',
'9,588,934.00') left no trace in note_lines (20250321001629 table 99: 4.5k JPY cells in the
verification campaign alone)."""
from __future__ import annotations

from pathlib import Path

from fin2.extract.report_lines import extract_report_lines

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>시장위험관리 환위험 (외화단위: USD, JPY, 원화단위: 천원)</P>
<TABLE>
<TR><TD>구분</TD><TD>외화종류</TD><TD>외화금액</TD><TD>원화환산금액</TD></TR>
<TR><TD ROWSPAN="3">현금및현금성자산</TD><TD>USD</TD><TD>6,193,584.95</TD><TD>9,104,570</TD></TR>
<TR><TD>JPY</TD><TD>9,588,934.00</TD><TD>89,798</TD></TR>
<TR><TD>EUR</TD><TD>-</TD><TD>1,200,000</TD></TR>
</TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _note_rows(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY",
                                 include_notes=True)
    return [l for l in lines if l.statement == "note"]


def test_unreadable_dot_cells_keep_a_null_row_with_the_printed_text(tmp_path):
    rows = _note_rows(tmp_path)
    raws = {l.value_raw: l for l in rows if l.value_raw}
    assert "6,193,584.95" in raws and "9,588,934.00" in raws
    for text in ("6,193,584.95", "9,588,934.00"):
        r = raws[text]
        assert r.value_won is None and r.adecimal is None        # never read as a number (R160)
        won_col = next(l.col_index for l in rows if l.value_won == 9104570000)
        assert r.col_index < won_col                             # the 외화금액 column, left of 원화환산


def test_the_readable_cells_are_unchanged(tmp_path):
    rows = _note_rows(tmp_path)
    won = sorted(l.value_won for l in rows if l.value_won is not None)
    assert 9104570000 in won and 89798000 in won and 1200000000 in won
    assert not any(l.value_raw for l in rows if l.value_won is not None)   # a read cell drops the raw
    # a dash is "no number" and still leaves no row
    assert all(l.value_raw != "-" for l in rows)
