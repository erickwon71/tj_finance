"""R296 - one source row that packs several logical rows into its cells (label cell 'a&cr;b&cr;c&cr;...', one
printed value per line in each value cell, empty lines kept; 삼영이엔씨 20171129000152 separate table 21).
The reader used to delete the `&cr;`, gluing the lines and losing the empty ones, so the whole row was taken
for a header row. The row is now split line by line when the label cell and every printed value cell have the
same number of lines; a row whose line counts differ is left as before."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines

HEAD = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 재무제표 주석</TITLE>
<P>금융상품 (단위: 원)</P>
<TABLE>
<TR><TD>재무상태표상 부채</TD><TD>당기손익인식&cr;금융부채</TD><TD>기타금융부채</TD><TD>합    계</TD></TR>
"""
TAIL = """<TR><TD>순손익</TD><TD>-</TD><TD>(39,381,286)</TD><TD>(39,381,286)</TD></TR>
</TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""
STACKED = ("<TR><TD>수익 &cr;  금융수익&cr;  기타이익&cr; 소계&cr;비용&cr; 금융원가&cr; 기타손실&cr; 소계</TD>"
           '<TD ALIGN="RIGHT">&cr;-&cr;-&cr;-&cr;&cr;-&cr;-&cr;-</TD>'
           '<TD ALIGN="RIGHT">&cr;101,259,961&cr;-&cr;101,259,961&cr;&cr;140,641,247&cr;-&cr;140,671,247</TD>'
           '<TD ALIGN="RIGHT">&cr;101,259,961&cr;-&cr;101,259,961&cr;&cr;140,641,247&cr;-&cr;140,671,247</TD></TR>\n')
MISMATCH = STACKED.replace("&cr;140,641,247&cr;-&cr;140,671,247</TD>\n", "&cr;140,641,247&cr;-&cr;140,671,247</TD>\n", 1)


def _rows(tmp_path, body):
    p = tmp_path / "n.xml"
    p.write_text(HEAD + body + TAIL, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY", include_notes=True)
    return [l for l in lines if l.statement == "note"]


def test_stacked_row_is_split_line_by_line(tmp_path):
    rows = _rows(tmp_path, STACKED)
    got = {(l.label_raw.strip(), l.col_index): l.value_won for l in rows}
    assert got[("수익>금융수익", 1)] == 101259961 and got[("수익>금융수익", 2)] == 101259961
    assert got[("수익>소계", 1)] == 101259961
    assert got[("비용>금융원가", 1)] == 140641247 and got[("비용>소계", 2)] == 140671247
    assert got[("순손익", 1)] == -39381286                       # the ordinary row below is unchanged
    assert not any("" in l.label_raw for l in rows)


def test_row_with_unequal_line_counts_is_not_split(tmp_path):
    body = STACKED.replace("&cr;-&cr;-&cr;-&cr;&cr;-&cr;-&cr;-", "&cr;-&cr;-&cr;-&cr;-&cr;-", 1)   # 6 lines vs 8
    rows = _rows(tmp_path, body)
    assert not any(l.label_raw.strip().startswith("수익>") for l in rows)
    assert not any("" in (l.label_raw or "") + (l.value_raw or "") for l in rows)
