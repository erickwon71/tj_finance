"""R304 - R296 for a row of exactly two lines: label 'a&cr;b' and every value cell 'x&cr;y' (대상 20151113000949
separate table 52: '설비자산&cr;(국고보조금)' | '227,478&cr;(816)'). Both label lines print text, every value cell prints
amounts, dashes or nothing on both lines; a lone '-' cell prints nothing. Anything else stays as before."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines

HEAD = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 재무제표 주석</TITLE>
<P>유형자산 (단위: 백만원)</P>
<TABLE>
<TR><TD>구분</TD><TD>기초</TD><TD>취득</TD><TD>기말</TD></TR>
<TR><TD>토지</TD><TD>208,840</TD><TD>-</TD><TD>208,363</TD></TR>
"""
TAIL = """<TR><TD>합계</TD><TD>454,323</TD><TD>55,793</TD><TD>482,308</TD></TR>
</TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""
TWO = "<TR><TD>설비자산&cr;(국고보조금)</TD><TD>227,478&cr;(816)</TD><TD>21,524&cr;-</TD><TD>229,183&cr;(511)</TD></TR>\n"


def _rows(tmp_path, body):
    p = tmp_path / "n.xml"
    p.write_text(HEAD + body + TAIL, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000002", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY", include_notes=True)
    return [l for l in lines if l.statement == "note"]


def test_two_line_row_is_split_line_by_line(tmp_path):
    got = {(l.label_raw.strip(), l.col_index): l.value_won for l in _rows(tmp_path, TWO)}
    assert got[("설비자산", 0)] == 227478000000 and got[("설비자산", 1)] == 21524000000
    assert got[("설비자산>(국고보조금)", 0)] == -816000000 and got[("설비자산>(국고보조금)", 2)] == -511000000
    assert got[("합계", 0)] == 454323000000                       # the rows around are unchanged


def test_two_line_row_with_a_text_value_cell_is_not_split(tmp_path):
    rows = _rows(tmp_path, TWO.replace("21,524&cr;-", "유동성&cr;단기"))
    assert not any(l.label_raw.strip() == "설비자산" for l in rows)


def test_two_line_row_whose_label_line_is_an_amount_is_not_split(tmp_path):
    rows = _rows(tmp_path, TWO.replace("설비자산&cr;(국고보조금)", "설비자산&cr;12,000"))
    assert not any(l.label_raw.strip() == "설비자산" and l.value_won == 227478000000 for l in rows)
