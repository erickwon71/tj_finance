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


XML_B = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>II. 사업의 내용</TITLE>
<P>(3) 종류주식 발행현황<A 우선주></P><P><E우선주></P>
<TABLE><COLGROUP><COL WIDTH="10"/></COLGROUP>
<TR><TD COLSPAN="2" ALIGN="CENTER">구분</TD><TD>값</TD></TR>
<TR><TD><P>Sensor bumping&</P><P>Glass 기판</P></TD><TD>1</TD></TR>
<TR><TD><The Big Door Prize></TD><TD>2</TD></TR></TABLE>
</SECTION-1></BODY></DOCUMENT>"""


def test_attributeless_angle_text_does_not_break_the_parse_r287b(tmp_path):
    """`<A 우선주>` is on sanitize_dart_xml's tag whitelist and made the whole document a parse
    error, after which libxml2 drops every later `&amp;` - only the biz reader escapes it."""
    p = tmp_path / "g.xml"
    p.write_text(XML_B, encoding="utf-8")
    root = _load_root(p)
    (table,) = list(root.iter("TABLE"))
    g = expand_table_grid(table)
    assert g[1][0].replace("\n", "") == "Sensor bumping&Glass 기판"
    assert g[2][0] == "<The Big Door Prize>"
    assert g[0][0] == "구분" and len(g[0]) == 3          # real tags with attributes are untouched
    texts = [x.text or "" for x in root.iter("P")]
    assert any("<E우선주>" in "".join(p.itertext()) for p in root.iter("P"))


def test_shared_sanitizer_is_unchanged_r287b():
    from parser.xml.dart_xml_parser import sanitize_dart_xml
    assert b"<A \xec\x9a\xb0\xec\x84\xa0\xec\xa3\xbc>" in sanitize_dart_xml("<P>x<A 우선주></P>".encode())
