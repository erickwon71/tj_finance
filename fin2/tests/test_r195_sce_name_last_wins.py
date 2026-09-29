"""R195 — the SCE name takes part in R141's 'last statement name wins' rule.

Shinyoung Securities 20181109000307 puts an SCE footnote and the next heading in one
paragraph ('※ …연결자본변동표는 …아니하였습니다.  라. 연결현금흐름표'). The note is
introduced by '※', which R161's note stripper does not know, and the classifier returned
SCE as soon as it saw the SCE name anywhere. The consolidated/separate CF tables were then
loaded as SCE and no CF was stored at all.
"""
from lxml import etree

from fin2.extract.statement_titles import classify_statement_in_body_section as classify
from fin2.extract.text import _detect_body_statement_tables

NOTE_SCE = "※ 당반기 연결자본변동표는 기업회계기준서 제1109호에 따라 작성되었으며, 비교표시된 연결자본변동표는 소급재작성되지 아니하였습니다."


def test_sce_footnote_followed_by_cf_heading_is_cf():
    assert classify(NOTE_SCE + " 라. 연결현금흐름표", include_sce=True) == "CF"


def test_sce_heading_after_other_footnote_is_still_sce():
    text = "※ 당반기 연결손익계산서는 소급재작성되지 아니하였습니다. 다. 연결자본변동표"
    assert classify(text, include_sce=True) == "SCE"


def test_plain_titles_unchanged():
    assert classify("연 결 자 본 변 동 표", include_sce=True) == "SCE"
    assert classify("연 결 자 본 변 동 표", include_sce=False) is None
    assert classify("연결현금흐름표", include_sce=True) == "CF"


def test_sce_footnote_followed_by_cf_heading_without_sce_opt_in_is_cf():
    """fact_v2 path (include_sce=False) must also see the CF table."""
    assert classify(NOTE_SCE + " 라. 연결현금흐름표", include_sce=False) == "CF"


PER = "제 65 기 반기 2018.04.01 부터 2018.09.30 까지"
SCE_TABLE = (
    "<TABLE>"
    "<TR><TD><P>과 목</P></TD><TD><P>자본금</P></TD><TD><P>이익잉여금</P></TD>"
    "<TD><P>기타포괄손익누계액</P></TD><TD><P>자본 계</P></TD></TR>"
    "<TR><TD><P>2018.04.01(기초)</P></TD><TD><P>1,550,000,000</P></TD><TD><P>2,533,388,000</P></TD>"
    "<TD><P>301,000,000</P></TD><TD><P>4,384,388,000</P></TD></TR>"
    "<TR><TD><P>2018.09.30(기말)</P></TD><TD><P>1,550,000,000</P></TD><TD><P>2,533,388,000</P></TD>"
    "<TD><P>301,000,000</P></TD><TD><P>4,384,388,000</P></TD></TR>"
    "</TABLE>")
CF_TABLE = (
    "<TABLE>"
    "<TR><TD><P>과 목</P></TD><TD><P>제 65 기</P></TD></TR>"
    "<TR><TD><P>영업활동현금흐름</P></TD><TD><P>1,000,000,000</P></TD></TR>"
    "<TR><TD><P>투자활동현금흐름</P></TD><TD><P>(500,000,000)</P></TD></TR>"
    "</TABLE>")


def test_detector_files_cf_table_under_merged_note_and_heading_as_cf():
    heading = f"<P><SPAN>{NOTE_SCE}</SPAN><SPAN>라. 연결현금흐름표 {PER}</SPAN></P>"
    doc = etree.fromstring(
        ("<DOCUMENT><SECTION-2><TITLE>2. 연결재무제표</TITLE>"
         f"<P>다. 연결자본변동표 {PER}</P>{SCE_TABLE}{heading}{CF_TABLE}"
         "</SECTION-2></DOCUMENT>").encode())
    groups = _detect_body_statement_tables(doc, "A", include_sce=True)
    assert len(groups.get("CF_C", [])) == 1
    assert len(groups.get("SCE_C", [])) == 1
    assert "자본금" in "".join(groups["SCE_C"][0][0].itertext())
