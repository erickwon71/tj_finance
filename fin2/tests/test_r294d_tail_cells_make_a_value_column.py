"""R294-d - (1) a column whose only amounts are 'amount + foreign tail' cells ('22,600,000 &cr;USD 4,300,000')
was never an amount column, so the label-area width (LV') swallowed it and the row labels became
'합계>32,350,000 USD 4,6' (금양 20161114000746 separate table 24); a tail cell now counts as a number
cell when the header boundary and the label-area width are decided. (2) the tail also accepts the yen /
euro / pound marks, '$' with decimals and a 1-2 digit amount behind a well-known ISO code."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines, split_amount_with_tail

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 재무제표 주석</TITLE>
<P>담보제공자산 (단위: 천원)</P>
<TABLE>
<TR><TD>담보제공자산</TD><TD>담보설정금액</TD><TD>관련계정과목</TD><TD>관련금액</TD></TR>
<TR><TD>토지</TD><TD>22,600,000 &cr;USD 4,300,000</TD><TD>차입금</TD><TD>29,772,027</TD></TR>
<TR><TD>건물</TD><TD>9,750,000 &cr;U</TD><TD></TD><TD>24,804,500</TD></TR>
<TR><TD>합계</TD><TD>32,350,000 &cr;USD 4,650,000 &cr;DEM 1,285,000</TD><TD></TD><TD>54,576,527</TD></TR>
</TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def test_tail_column_is_a_value_column(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY", include_notes=True)
    rows = [l for l in lines if l.statement == "note"]
    total = {l.col_index: l for l in rows if l.label_raw.strip() == "합계"}
    assert total and total[min(total)].value_won == 32350000000, [(l.label_raw, l.col_index, l.value_won) for l in rows]
    assert {l.label_raw.strip() for l in rows} >= {"토지", "건물", "합계"}


def test_more_tail_marks():
    f = split_amount_with_tail
    assert f("15,671,751 (￥179,312,180) ($4,294,383.44)") == "15,671,751"
    assert f("50,832,521 USD 5,548 EUR 41") == "50,832,521"
    assert f("1,000 €2,000 £300") == "1,000"
    assert f("1,234 NO 5") is None and f("6,000\n USD 1,2 (주1)") is None
    assert f("11,700,993 (US$ 5,717,069 포함)") is None
