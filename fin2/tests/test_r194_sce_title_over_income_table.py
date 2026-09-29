"""R194 — an SCE title over an income-statement table must not load that table as SCE.

DKnD 20190401005200 prints the consolidated income statement under a title that reads
'연결자본변동표', then prints the real equity-changes title and table right after it.
The title-only/data-table forward scan linked the income table as SCE data (66 spurious
SCE rows). R127 guards the mirror case (SCE data under an IS/CF/BS title).
"""
from lxml import etree

from fin2.extract.text import (
    _detect_body_statement_tables,
    _looks_like_income_or_cashflow_face,
)

PER = "제 19 기 2018.01.01 부터 2018.12.31 까지"


def _title(text: str) -> str:
    return f"<TABLE><TR><TD><P>{text}</P></TD></TR></TABLE>"


IS_TABLE = (
    "<TABLE>"
    "<TR><TD><P>과 목</P></TD><TD><P>제 19 기</P></TD></TR>"
    "<TR><TD><P>I. 매출액</P></TD><TD><P>54,765,341,149</P></TD></TR>"
    "<TR><TD><P>IV. 영업이익</P></TD><TD><P>3,685,808,084</P></TD></TR>"
    "<TR><TD><P>VII. 당기순이익</P></TD><TD><P>3,731,735,012</P></TD></TR>"
    "</TABLE>")

SCE_TABLE = (
    "<TABLE>"
    "<TR><TD><P>과 목</P></TD><TD><P>자본금</P></TD><TD><P>이익잉여금</P></TD>"
    "<TD><P>기타포괄손익누계액</P></TD><TD><P>자본 계</P></TD></TR>"
    "<TR><TD><P>2018.01.01(기초)</P></TD><TD><P>1,550,000,000</P></TD><TD><P>2,533,388,000</P></TD>"
    "<TD><P>301,000,000</P></TD><TD><P>4,384,388,000</P></TD></TR>"
    "<TR><TD><P>2018.12.31(기말)</P></TD><TD><P>1,550,000,000</P></TD><TD><P>2,533,388,000</P></TD>"
    "<TD><P>301,000,000</P></TD><TD><P>4,384,388,000</P></TD></TR>"
    "</TABLE>")

CF_TABLE = (
    "<TABLE>"
    "<TR><TD><P>과 목</P></TD><TD><P>제 19 기</P></TD></TR>"
    "<TR><TD><P>영업활동현금흐름</P></TD><TD><P>1,000,000,000</P></TD></TR>"
    "<TR><TD><P>투자활동현금흐름</P></TD><TD><P>(500,000,000)</P></TD></TR>"
    "</TABLE>")


def _doc(*tables: str) -> etree._Element:
    return etree.fromstring(
        ("<DOCUMENT><SECTION-2><TITLE>2. 연결재무제표</TITLE>"
         + "".join(tables) + "</SECTION-2></DOCUMENT>").encode())


def _sce_tables(groups) -> list:
    return [t for t, _u, _k in groups.get("SCE_C", [])]


def test_predicate_flags_income_and_cashflow_but_not_sce():
    assert _looks_like_income_or_cashflow_face(etree.fromstring(IS_TABLE)) is True
    assert _looks_like_income_or_cashflow_face(etree.fromstring(CF_TABLE)) is True
    assert _looks_like_income_or_cashflow_face(etree.fromstring(SCE_TABLE)) is False


def test_income_table_under_sce_title_is_not_loaded_as_sce():
    """★핵심 — 첫 SCE 표제 뒤 IS 표는 건너뛰고, 두 번째 표제 아래 진짜 SCE 만 남는다."""
    doc = _doc(_title(f"연결자본변동표 {PER}"), IS_TABLE,
               _title(f"연 결 자 본 변 동 표 {PER}"), SCE_TABLE)
    tables = _sce_tables(_detect_body_statement_tables(doc, "A", include_sce=True))
    assert len(tables) == 1
    assert "자본금" in "".join(tables[0].itertext())
    assert "매출액" not in "".join(tables[0].itertext())


def test_cashflow_table_under_sce_title_is_not_loaded_as_sce():
    doc = _doc(_title(f"연결자본변동표 {PER}"), CF_TABLE,
               _title(f"연결자본변동표 {PER}"), SCE_TABLE)
    tables = _sce_tables(_detect_body_statement_tables(doc, "A", include_sce=True))
    assert len(tables) == 1 and "자본금" in "".join(tables[0].itertext())


def test_normal_sce_is_untouched():
    """가드가 정상 SCE 를 약화·유실시키지 않는다(가산적 수정 확인)."""
    doc = _doc(_title(f"연결자본변동표 {PER}"), SCE_TABLE)
    tables = _sce_tables(_detect_body_statement_tables(doc, "A", include_sce=True))
    assert len(tables) == 1
