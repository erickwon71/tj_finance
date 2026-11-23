"""R380 — `[첨부정정]사업보고서` 의 첨부 감사보고서 XML 에서 재무제표를 읽는다 (합성 XML, DB 비의존).

배경: 첨부정정 XML 은 사업보고서 본문이 아니라 `독립된 감사인의 감사보고서` + `(첨부)재 무 제 표`
SECTION-1 + `주석` SECTION-2 로 이루어진다. `2.연결재무제표`/`4.재무제표` 가 없고 구형 컨테이너
(`재무제표등`·`부속명세서`)도 없어서 본문 섹션이 0개였다(알루코 20150327000685 등 FY2014 7필링,
계층2 0행). 규칙: docs/rules/10_layer2_parse.md R380.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree  # noqa: E402

from fin2.extract.text import _detect_legacy_body_statement_tables  # noqa: E402


def _data_table(*rows):
    trs = "".join(
        f"<TR><TD><P>{label}</P></TD><TD><P>{amount}</P></TD></TR>" for label, amount in rows)
    return f"<TABLE>{trs}</TABLE>"


def _heading(text):
    return f"<TABLE><TR><TD><P>{text}</P></TD></TR></TABLE>"


_NOTE_TABLE = _data_table(("토지", "888,888,888"), ("건물", "444,555,666"))


def _audit_doc(container_title, prefix=""):
    return f"""<DOCUMENT><BODY>
 <SECTION-1><TITLE>독립된 감사인의 감사보고서</TITLE>
  {_data_table(("감사의견", "1,000,000,001"))}
 </SECTION-1>
 <SECTION-1><TITLE>{container_title}</TITLE>
  {_heading(prefix + "재 무 상 태 표 제59(당)기말 2014년 12월 31일 현재 (단위 : 원)")}
  {_data_table(("자산총계", "1,111,111,111"), ("부채총계", "222,222,222"))}
  {_heading("별첨 주석 참조")}
  {_heading(prefix + "포 괄 손 익 계 산 서 제59(당)기 2014년 1월 1일부터 2014년 12월 31일까지")}
  {_data_table(("매출액", "3,333,333,333"), ("영업이익", "444,444,444"))}
  {_heading(prefix + "현 금 흐 름 표 제59(당)기 2014년 1월 1일부터 2014년 12월 31일까지")}
  {_data_table(("영업활동현금흐름", "555,555,555"), ("투자활동현금흐름", "-66,666,666"))}
  <SECTION-2><TITLE>주석</TITLE>
   <P>4. 유형자산</P>
   {_NOTE_TABLE}
  </SECTION-2>
 </SECTION-1>
</BODY></DOCUMENT>"""


def _amounts(groups, code):
    out = set()
    for tbl, _unit, _kind in groups.get(code, []):
        out.update(t.strip() for t in tbl.itertext() if "," in t)
    return out


def test_separate_attachment_is_read_as_separate_statements():
    root = etree.fromstring(_audit_doc("(첨부)재 무 제 표").encode())
    groups = _detect_legacy_body_statement_tables(root, "A", include_sce=True)
    assert "1,111,111,111" in _amounts(groups, "BS_S")
    assert "3,333,333,333" in _amounts(groups, "IS_S")
    assert "555,555,555" in _amounts(groups, "CF_S")
    assert not any(code.endswith("_C") for code in groups)


def test_consolidated_attachment_is_read_as_consolidated_statements():
    root = etree.fromstring(_audit_doc("(첨부)연 결 재 무 제 표", prefix="연 결 ").encode())
    groups = _detect_legacy_body_statement_tables(root, "A", include_sce=True)
    assert "1,111,111,111" in _amounts(groups, "BS_C")
    assert "3,333,333,333" in _amounts(groups, "IS_C")
    assert "555,555,555" in _amounts(groups, "CF_C")
    assert not any(code.endswith("_S") for code in groups)


def test_note_section_tables_are_never_picked():
    root = etree.fromstring(_audit_doc("(첨부)재 무 제 표").encode())
    groups = _detect_legacy_body_statement_tables(root, "A", include_sce=True)
    picked = {a for code in groups for a in _amounts(groups, code)}
    assert "888,888,888" not in picked
    assert "1,000,000,001" not in picked      # the audit-opinion section is not a statement


def test_document_without_any_container_still_returns_empty():
    doc = """<DOCUMENT><BODY><SECTION-1><TITLE>독립된 감사인의 감사보고서</TITLE>
      <TABLE><TR><TD><P>재 무 상 태 표</P></TD></TR></TABLE>
      <TABLE><TR><TD><P>자산총계</P></TD><TD><P>1,111,111,111</P></TD></TR></TABLE>
    </SECTION-1></BODY></DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    assert _detect_legacy_body_statement_tables(root, "A", include_sce=True) == {}


def test_existing_legacy_container_still_wins():
    """`재무제표등` 컨테이너가 있으면 첨부 컨테이너는 보지 않는다(기존 동작 무변경)."""
    doc = f"""<DOCUMENT><BODY>
     <SECTION-1><TITLE>XI. 재무제표 등</TITLE>
      {_heading("재 무 상 태 표 제59(당)기말 2014년 12월 31일 현재 (단위 : 원)")}
      {_data_table(("자산총계", "7,777,777,777"), ("부채총계", "777,777,777"))}
     </SECTION-1>
     <SECTION-1><TITLE>(첨부)재 무 제 표</TITLE>
      {_heading("재 무 상 태 표 제59(당)기말 2014년 12월 31일 현재 (단위 : 원)")}
      {_data_table(("자산총계", "1,111,111,111"), ("부채총계", "111,111,111"))}
     </SECTION-1></BODY></DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    groups = _detect_legacy_body_statement_tables(root, "A", include_sce=True)
    assert _amounts(groups, "BS_S") == {"7,777,777,777", "777,777,777"}
