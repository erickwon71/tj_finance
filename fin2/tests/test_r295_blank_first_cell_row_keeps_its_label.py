"""R295 - a note-table row whose FIRST physical cell is blank ('' / spaces / U+3000, not a ROWSPAN) but
whose second label-area cell has text ('리스부채 합계', '합 계') was dropped whole by _grid_body_rows
(`label = physical[0].text` -> `if not label: continue`), e.g. 20230814002069 consolidated table 85 and
20171114001696 separate table 80 (found by the verification scope note machine: the total row was the
only row of its table missing). The note path now takes the '>'-joined text of the label-area cells as the
label; the SCE path is unchanged."""
from __future__ import annotations

import pytest

from fin2.extract.report_lines import extract_report_lines

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>리스 (단위: 천원)</P>
<TABLE>
<TR><TD>구분</TD><TD>내역</TD><TD>당반기말</TD><TD>전기말</TD></TR>
<TR><TD ROWSPAN="2">유동성리스부채</TD><TD>리스부채</TD><TD>401,715</TD><TD>389,800</TD></TR>
<TR><TD>비유동</TD><TD>1,000</TD><TD>2,000</TD></TR>
<TR><TD>BLANK</TD><TD>LABEL</TD><TD>1,166,100</TD><TD>442,645</TD></TR>
</TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _rows(tmp_path, blank, label="리스부채 합계"):
    p = tmp_path / "n.xml"
    p.write_text(XML.replace("BLANK", blank).replace("LABEL", label), encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY",
                                 include_notes=True)
    return [l for l in lines if l.statement == "note"]


@pytest.mark.parametrize("blank", ["", " ", "　"])
def test_total_row_with_blank_first_cell_is_kept(tmp_path, blank):
    rows = _rows(tmp_path, blank)
    total = {l.col_index: l for l in rows if "리스부채 합계" in l.label_raw}
    assert total[0].value_won == 1166100000 and total[1].value_won == 442645000, rows
    assert total[0].label_raw.strip() == "리스부채 합계"


def test_other_rows_are_unchanged(tmp_path):
    rows = _rows(tmp_path, "　")
    first = {l.col_index: l for l in rows if l.row_order == 0}
    assert first[0].value_won == 401715000 and first[1].value_won == 389800000
    assert any(l.value_won == 1000000 for l in rows)


def test_row_with_an_empty_label_area_is_still_dropped(tmp_path):
    rows = _rows(tmp_path, "　", label="　")
    assert not any(l.value_won == 1166100000 for l in rows)
