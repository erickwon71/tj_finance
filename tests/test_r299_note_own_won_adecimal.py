"""R299 - a note cell with its own won suffix gets adecimal 0 although the table declares 천원."""
from pathlib import Path

import fin2.extract.report_lines as rl

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>17. 자본금</P>
<TABLE><TR><TD>(단위: 천원)</TD></TR></TABLE>
<TABLE><TR><TD>구분</TD><TD>당분기말</TD><TD>전기말</TD></TR>
<TR><TD>유형자산</TD><TD>517,179</TD><TD>512,679</TD></TR>
<TR><TD>자본금</TD><TD>3,265,007,000원</TD><TD>3,265,007,000원</TD></TR></TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _rows(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    ls = rl.extract_report_lines(Path(p), rcept_no="20240101000001", corp_code="00000001",
                                 report_fiscal_year=2023, report_fiscal_period="FY", include_notes=True)
    return {(l.label_raw, l.col_index): l for l in ls if l.statement == "note"}


def test_own_won_cell_has_adecimal_zero_and_bare_cell_keeps_the_table_unit(tmp_path):
    r = _rows(tmp_path)
    assert r[("자본금", 0)].value_won == 3265007000 and r[("자본금", 0)].adecimal == 0
    assert r[("유형자산", 0)].value_won == 517179000 and r[("유형자산", 0)].adecimal == -3


def test_switch_off_restores_the_old_adecimal(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "_R299_NOTE_OWN_WON_ADECIMAL", False)
    assert _rows(tmp_path)[("자본금", 0)].adecimal == -3
