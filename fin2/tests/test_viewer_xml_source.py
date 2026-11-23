"""Web-viewer print as the layer-2 source of filings without a main XML (2026-10-10,
docs/plans/viewer_xml_source_policy_2026-10-10.md)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from collector import viewer_source as vs  # noqa: E402
from fin2.extract.report_lines import extract_report_lines  # noqa: E402
from fin2.extract.viewer_xml import build_document, is_statement_section  # noqa: E402

_SECTION = """<HTML><BODY>
<P class='section-2'><A name='toc1'>4. 재무제표</A></P>
<TABLE class='nb'><TBODY>
<TR><TD><P>재무상태표</P></TD></TR>
<TR><TD><P>제 26 기 반기말 2015.06.30 현재</P></TD></TR>
<TR><TD><P>(단위 : 원)</P></TD></TR>
</TBODY></TABLE>
<TABLE border='1'>
<THEAD><TR><TH>　</TH><TH><P>제 26 기 반기말</P></TH><TH><P>제 25 기말</P></TH></TR></THEAD>
<TBODY>
<TR><TD><P>자산</P></TD><TD>　</TD><TD>　</TD></TR>
<TR><TD><P>　유동자산</P></TD><TD><P>1,000</P></TD><TD><P>900</P></TD></TR>
<TR><TD><P>　　매출채권</P></TD><TD><P>1,073</P></TD><TD><P>973</P></TD></TR>
<TR><TD><P>　　대손충당금</P></TD><TD><P>(73)</P></TD><TD><P>(73)</P></TD></TR>
<TR><TD><P>자산총계</P></TD><TD><P>1,000</P></TD><TD><P>900</P></TD></TR>
<TR><TD><P>부채총계</P></TD><TD><P>400</P></TD><TD><P>300</P></TD></TR>
<TR><TD><P>자본총계</P></TD><TD><P>600</P></TD><TD><P>600</P></TD></TR>
</TBODY></TABLE>
</BODY></HTML>"""


def test_viewer_print_reads_parentheses_as_printed(tmp_path):
    xml = build_document([("4. 재무제표", _SECTION.encode("utf-8"))])
    p = tmp_path / "KOSDAQ" / "00000001_T" / "half" / "2015" / "20150827000474.viewer.xml"
    p.parent.mkdir(parents=True)
    p.write_bytes(xml)
    lines = extract_report_lines(str(p), rcept_no="20150827000474", corp_code="00000001",
                                 report_fiscal_year=2015, report_fiscal_period="H1", include_notes=False)
    got = {l.label_raw.strip(): l.value_won for l in lines
           if l.statement == "BS" and l.col_index == 0}
    assert got.get("대손충당금") == -73 and got.get("자산총계") == 1000


_P_TITLED = """<HTML><BODY>
<P class='section-2'><A name='toc1'>4. 재무제표</A></P>
<P><BR></P>
<P><SPAN>1) 재무상태표</SPAN><BR></P>
<P><BR></P>
<P>   제 15기  1분기말  2018.03.31 현재<BR>   제 14기  전기말  2017.12.31 현재<BR>   (단위: 원)</P>
<TABLE BORDER='1'><TBODY>
<TR><TD>과 목</TD><TD>제 15 기 1분기</TD><TD>제 14 기 연간</TD></TR>
<TR><TD>유동자산</TD><TD>1,000</TD><TD>900</TD></TR>
<TR><TD>Ⅴ. 이익잉여금<BR></TD><TD>600</TD><TD>600</TD></TR>
<TR><TD>자산총계</TD><TD>1,000</TD><TD>900</TD></TR>
</TBODY></TABLE>
</BODY></HTML>"""


def test_line_breaks_are_dropped_like_dart_cr(tmp_path):
    """<BR> = DART's `&cr;`, which the DART XML reader deletes; kept, it became the text '<BR/>'
    in labels and hid paragraph titles (20180906000287 티로보틱스: 0 rows)."""
    xml = build_document([("4. 재무제표", _P_TITLED.encode("utf-8"))])
    assert b"<BR" not in xml
    p = tmp_path / "20180906000287.viewer.xml"
    p.write_bytes(xml)
    lines = extract_report_lines(str(p), rcept_no="20180906000287", corp_code="00867098",
                                 report_fiscal_year=2018, report_fiscal_period="Q1", include_notes=False)
    got = {l.label_raw.strip(): l.value_won for l in lines if l.statement == "BS" and l.col_index == 0}
    assert got.get("자산총계") == 1000 and got.get("Ⅴ. 이익잉여금") == 600


def test_strip_line_breaks_keeps_tail_text():
    from lxml import etree
    from fin2.extract.viewer_xml import strip_line_breaks
    root = etree.fromstring("<P>a<BR/>b<SPAN>c</SPAN><BR/>d<BR/></P>")
    assert strip_line_breaks(root) == 3
    assert etree.tostring(root) == b"<P>ab<SPAN>c</SPAN>d</P>"


def test_statement_sections_and_signature():
    assert is_statement_section("4. 재무제표") and is_statement_section("3. 연결재무제표 주석")
    assert not is_statement_section("1. 요약재무정보") and not is_statement_section("6. 기타 재무에 관한 사항")

    class N:
        def __init__(self, text, length):
            self.text, self.length = text, length
    a = vs.signature([(x.text, x) for x in (N("4. 재무제표", "186944"), N("5. 재무제표 주석", "244431"))])
    b = vs.signature([(x.text, x) for x in (N("4. 재무제표", "186945"), N("5. 재무제표 주석", "244431"))])
    assert a and b and a != b and vs.signature([]) is None


def test_viewer_file_never_takes_the_package_name(tmp_path, monkeypatch):
    class N:
        text, length, dcm_no, ele_id, offset, dtd = "4. 재무제표", "10", "1", "17", "0", "dart3.xsd"

    class Scraper:
        def fetch_viewer_section(self, *a, **k):
            return _SECTION.encode("utf-8")
    path, sig = vs.build_viewer_xml(Scraper(), "20150827000474", str(tmp_path / "x.placeholder"), [("4. 재무제표", N())])
    assert path.endswith("20150827000474.viewer.xml") and sig


def test_attachment_layout_maps_to_standard_titles():
    from fin2.extract.viewer_xml import select_sections

    class N:
        def __init__(self, text):
            self.text = text
    nodes = [N(t) for t in ("정 정 신 고 (보고)", "반기연결재무제표 검토보고서", "(첨부)반 기 연 결 재 무 제 표", "주석")]
    assert [t for t, _ in select_sections(nodes)] == ["2. 연결재무제표", "3. 연결재무제표 주석"]
    std = [N(t) for t in ("1. 요약재무정보", "2. 연결재무제표", "3. 연결재무제표 주석", "4. 재무제표", "5. 재무제표 주석")]
    assert [t for t, _ in select_sections(std)] == ["2. 연결재무제표", "3. 연결재무제표 주석", "4. 재무제표", "5. 재무제표 주석"]


def test_viewer_source_loads_pre2015_filings():
    """2026-11-23: viewer-source filings load from FY1999, not the XBRL FY_MIN (2015) — 1,404
    pre-2015 PDF-only filings had no layer-2 rows because every viewer filter said 2015."""
    import inspect
    from collector import viewer_source, xbrl_instance_lines_sync as sync
    assert viewer_source.VIEWER_FY_MIN <= 1999
    assert inspect.signature(sync.sync_viewer_lines).parameters["year_min"].default == viewer_source.VIEWER_FY_MIN


# ---- R381: section titles follow what the body prints, not the TOC node text ----
def _doc(*sections):
    """sections: (title, [element xml strings]) -> DOCUMENT tree."""
    from lxml import etree
    xml = "<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>"
    for title, els in sections:
        xml += f"<SECTION-2><TITLE ATOC=\"Y\">{title}</TITLE>{''.join(els)}</SECTION-2>"
    return etree.fromstring(xml + "</SECTION-1></BODY></DOCUMENT>")


def _titles(doc):
    return [s.findtext("TITLE") for s in doc.iter("SECTION-2")]


_C_HEAD = "<TABLE><TR><TD>반 기 연 결 재 무 상 태 표 제60(당)기 반기 2014년 06월 30일 현재</TD></TR></TABLE>"
_S_HEAD = "<TABLE><TR><TD>재무상태표 제17기 반기말 2014.06.30 현재</TD></TR></TABLE>"
_NOTE = "<P>1. 일반사항</P>"


def test_r381_consolidated_body_under_plain_title_is_retitled_and_its_notes_follow():
    """BYC 20140829001554 / 대신증권 20141121000333: TOC node '반 기 재 무 제 표' held 연결 statements."""
    from fin2.extract.viewer_xml import fix_basis_titles
    doc = _doc(("4. 재무제표", [_C_HEAD]), ("4. 재무제표", [_NOTE]))
    assert fix_basis_titles(doc) == 2
    assert _titles(doc) == ["2. 연결재무제표", "3. 연결재무제표 주석"]


def test_r381_title_only_paragraph_heading_counts():
    """대신증권: the heading is a title-only <P> ('분기연결재무상태표'), the period line is the next table."""
    from fin2.extract.viewer_xml import fix_basis_titles
    doc = _doc(("4. 재무제표", ['<P>"검토를 받은 분기재무제표"</P>', "<P>분 기 연 결 재 무 상 태 표</P>"]))
    assert fix_basis_titles(doc) == 1
    assert _titles(doc) == ["2. 연결재무제표"]


def test_r381_mixed_section_is_split_at_the_basis_change():
    """한성크린텍 20150730000147: 'XI. 재무제표 등' printed 연결 statements then 별도 ones."""
    from fin2.extract.viewer_xml import fix_basis_titles
    doc = _doc(("XI. 재무제표 등", ["<P>XI. 재무제표 등</P>", _C_HEAD, "<TABLE/>", _S_HEAD, "<TABLE/>"]))
    assert fix_basis_titles(doc) == 1
    assert _titles(doc) == ["2. 연결재무제표", "4. 재무제표"]
    cons, sep = list(doc.iter("SECTION-2"))
    assert "연 결" in "".join(cons.itertext()) and "재무상태표 제17기" in "".join(sep.itertext())
    assert "재무상태표 제17기" not in "".join(cons.itertext())


def test_r381_separate_only_print_and_correct_titles_are_untouched():
    from fin2.extract.viewer_xml import fix_basis_titles
    plain = _doc(("4. 재무제표", [_S_HEAD]), ("4. 재무제표", [_NOTE]))
    assert fix_basis_titles(plain) == 0 and _titles(plain) == ["4. 재무제표", "4. 재무제표"]
    right = _doc(("2. 연결재무제표", [_C_HEAD]), ("4. 재무제표", [_C_HEAD, _S_HEAD]))
    assert fix_basis_titles(right) == 0 and _titles(right) == ["2. 연결재무제표", "4. 재무제표"]


def test_r381_note_text_is_not_a_heading():
    from fin2.extract.viewer_xml import fix_basis_titles
    doc = _doc(("4. 재무제표", [_S_HEAD, "<P>재무상태표 상 순재산액은 자산총계에서 차감한 금액입니다. 현재</P>"]))
    assert fix_basis_titles(doc) == 0


def test_r381_review_report_notes_node_is_not_a_statement_section():
    from fin2.extract.viewer_xml import select_sections

    class N:
        def __init__(self, text):
            self.text = text
    nodes = [N(t) for t in ("검 토 보 고 서", "반 기 재 무 제 표", "반기재무제표에 대한 주석")]
    assert [t for t, _ in select_sections(nodes)] == ["4. 재무제표", "5. 재무제표 주석"]


def test_r381_build_document_applies_the_fix():
    sec = '<html><body><table><tr><td>반 기 연 결 재 무 상 태 표 제60(당)기 반기 2014년 06월 30일 현재</td></tr></table></body></html>'
    xml = build_document([("4. 재무제표", sec.encode("utf-8"))])
    assert "<TITLE ATOC=\"Y\">2. 연결재무제표</TITLE>" in xml.decode("utf-8")
