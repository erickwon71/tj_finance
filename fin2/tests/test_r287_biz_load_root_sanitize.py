"""R287 — the '사업의 내용' reader sanitizes the DART XML before parsing (as R224 does for the
statements): a bare '&' / '<' in a cell must survive, not swallow the text after it."""
from __future__ import annotations

from fin2.extract.biz_section import _load_root, expand_table_grid

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>II. 사업의 내용</TITLE>
<TABLE><TR><TD>부 문</TD><TD>제56기</TD></TR>
<TR><TD>H&B사업본부</TD><TD>1,000</TD></TR>
<TR><TD>당진L&S1기</TD><TD>2,000</TD></TR>
<TR><TD><연구인력현황></TD><TD>5&cr;6</TD></TR></TABLE>
</SECTION-1></BODY></DOCUMENT>"""


def _grid(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(XML, encoding="utf-8")
    root = _load_root(p)
    (table,) = list(root.iter("TABLE"))
    return expand_table_grid(table)


def test_bare_ampersand_and_lt_survive(tmp_path):
    g = _grid(tmp_path)
    assert g[1][0] == "H&B사업본부"
    assert g[2][0] == "당진L&S1기"
    assert g[3][0] == "<연구인력현황>"


def test_cr_marker_is_still_dropped(tmp_path):
    assert _grid(tmp_path)[3][1].replace("\n", "") == "56"
