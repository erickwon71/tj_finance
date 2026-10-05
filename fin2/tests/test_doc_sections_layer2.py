"""API→문서 전환 Phase 0 — layer-2 doc_section_tables extractor (fin2/layer2/doc_sections.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree

from fin2.layer2.doc_sections import extract_doc_section_tables

_DOC = """<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
  <SECTION-2><TITLE>6. 배당에 관한 사항</TITLE>
    <P>가. 배당정책</P>
    <TABLE><TBODY><TR><TD>구분</TD><TD>현황</TD></TR><TR><TD>결정기관</TD><TD>이사회</TD></TR></TBODY></TABLE>
    <TABLE-GROUP ACLASS="DIVIDEND">
      <TABLE><TBODY><TR><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>
      <TABLE><TBODY>
        <TR><TD ROWSPAN="2">구분</TD><TD ROWSPAN="2">주식의 종류</TD><TD>당기</TD></TR>
        <TR><TD>제64기</TD></TR>
        <TR><TD>주당 현금배당금(원)</TD><TD>보통주</TD><TD>3,300</TD></TR>
      </TBODY></TABLE>
    </TABLE-GROUP>
    <TABLE-GROUP ACLASS="DIVIDEND_BCK"><TABLE><TBODY><TR><TD>연속 배당횟수</TD></TR></TBODY></TABLE></TABLE-GROUP>
  </SECTION-2>
</SECTION-1>
<SECTION-1><TITLE>VII. 주주에 관한 사항</TITLE>
  <TABLE><TBODY><TR><TD>종류</TD><TD>7월</TD></TR><TR><TD>보통주</TD><TD>1,000</TD></TR></TBODY></TABLE>
</SECTION-1>
<SECTION-1><TITLE>VI. 주주총회 등에 관한 사항</TITLE>
  <TABLE><TBODY><TR><TD>주총일자</TD><TD>안건</TD></TR><TR><TD>2025.3.1</TD><TD>x</TD></TR></TBODY></TABLE>
</SECTION-1>
<SECTION-1><TITLE>II. 사업의 내용</TITLE>
  <TABLE><TBODY><TR><TD>제품</TD><TD>매출</TD></TR><TR><TD>라면</TD><TD>1</TD></TR></TBODY></TABLE>
</SECTION-1>
</BODY></DOCUMENT>"""


def _tables():
    return extract_doc_section_tables(etree.fromstring(_DOC))


def test_target_aclass_group_tables_in_order():
    div = [t for t in _tables() if t.aclass == "DIVIDEND"]
    assert [t.group_ord for t in div] == [0, 1]
    assert div[0].grid == [["(단위 : 백만원)"]]
    assert div[1].section_key == "배당에관한사항"
    assert div[1].heading_raw == "가. 배당정책"


def test_rowspan_expanded_grid():
    div = [t for t in _tables() if t.aclass == "DIVIDEND"][1]
    assert div.grid[1][:2] == ["구분", "주식의 종류"]
    assert div.grid[2] == ["주당 현금배당금(원)", "보통주", "3,300"]


def test_non_target_aclass_skipped():
    assert not [t for t in _tables() if t.aclass == "DIVIDEND_BCK"]


def test_title_fallback_keeps_orphans_in_target_sections_only():
    orphans = [t for t in _tables() if t.aclass is None]
    assert {t.section_key for t in orphans} == {"배당에관한사항", "주주에관한사항"}


def test_table_ord_is_dense_document_order():
    ts = _tables()
    assert [t.table_ord for t in ts] == list(range(len(ts)))
