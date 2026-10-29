"""R293 - R158/R158-b ('.'-broken thousands separator restored from an integer pair of the same row)
must not run in a NON-MONETARY column. A contract rate '1,214.00' next to the amount '12,140,000'
(= USD 10,000,000 x 1,214 in 천원) is a prefix of that integer with an all-zero tail, so the rule
REPLACED the printed rate by 12140000 (20221111000671 table 13, 계약환율 column; 82 such unit_scale
issues in the note campaign). Printed values only (R0-2): the rate stays '1,214.00' in value_raw."""
from __future__ import annotations

from parser.xml.table_extractor import _repair_dot_grouped_cells
from fin2.extract.report_lines import extract_report_lines

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>통화선도 내역 (단위 : 천원, USD)</P>
<TABLE>
<TR><TD>계약처</TD><TD>매입금액</TD><TD>매도금액</TD><TD>계약환율</TD><TD>평가이익</TD></TR>
<TR><TD>수협은행</TD><TD>USD 10,000,000</TD><TD>12,140,000</TD><TD>1,214.00</TD><TD>2,208,000</TD></TR>
<TR><TD>우리은행</TD><TD>USD 602,049</TD><TD>767,613</TD><TD>1,275.00</TD><TD>96,207</TD></TR>
</TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def test_repair_skips_the_given_columns():
    cells = ["12,140,000", "1,214.00", "2,208,000"]
    assert _repair_dot_grouped_cells(cells)[1] == "12140000"                  # the old, wrong reading
    assert _repair_dot_grouped_cells(cells, None, frozenset({1}))[1] == "1,214.00"
    cells2 = ["42,549,493", "42,549.493"]                                     # a real broken cell is still restored
    assert _repair_dot_grouped_cells(cells2, None, frozenset())[1] == "42549493"


def test_contract_rate_keeps_its_printed_text(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    rows = [l for l in extract_report_lines(
        p, rcept_no="29990101000001", corp_code="99000001", report_fiscal_year=2024,
        report_fiscal_period="FY", include_notes=True) if l.statement == "note"]
    rates = {l.value_raw for l in rows if l.value_raw}
    assert "1,214.00" in rates and "1,275.00" in rates, rates
    assert not any(l.value_raw in ("12140000", "12750000") for l in rows)
    assert all(l.value_won is None for l in rows if l.value_raw in ("1,214.00", "1,275.00"))
    assert any(l.value_won == 12140000000 for l in rows)                      # 매도금액 read as before
