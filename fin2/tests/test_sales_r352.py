"""R352 sales-table finder regression tests (layer 2 reading, DB-free).

Mini documents mirror the FY2025 annual reports whose sales table was not found:
덕산네오룩스 20260318001436 (fused heading), 성도이엔지 20260319001406 (sub-heading wording),
누리플렉스 20260318000419 (table straight under the section TITLE), 나무AX 20260727000316 (window ran
past the next TITLE).
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.sales_section import (  # noqa: E402
    _is_sales_heading,
    find_sales_subsections,
    map_sales_table,
)

_SALES_TABLE = """<TABLE><TBODY>
<TR><TD>매출유형</TD><TD>품목</TD><TD>제12기</TD><TD>제11기</TD></TR>
<TR><TD>제품</TD><TD>소재</TD><TD>147,041</TD><TD>165,021</TD></TR>
<TR><TD>합계</TD><TD>합계</TD><TD>147,041</TD><TD>165,021</TD></TR>
</TBODY></TABLE>"""
_UNIT = "<TABLE><TBODY><TR><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>"
_RND_TABLE = """<TABLE><TBODY>
<TR><TD>no</TD><TD>연구명</TD><TD>연구기간</TD></TR>
<TR><TD>1</TD><TD>AI 플랫폼</TD><TD>2,024</TD></TR>
</TBODY></TABLE>"""


def _doc(body: str):
    return etree.fromstring(f"<DOCUMENT><BODY>{body}</BODY></DOCUMENT>".encode())


def _heads(root):
    return [t.grid[0][0] for t in find_sales_subsections(root)]


def test_fused_heading_does_not_cut_its_own_window():
    # "가. 매출 상황(1) 매출실적" <P> holds a "가. 매출 상황" <SPAN>; that SPAN is the heading's own text.
    root = _doc('<TITLE>4. 매출 및 수주상황</TITLE>'
                '<P><SPAN>가. 매출 상황</SPAN>(1) 매출실적</P>'
                f'{_UNIT}{_SALES_TABLE}<P>나. 수주 상황</P>')
    tables = find_sales_subsections(root)
    assert [t.grid[0][0] for t in tables] == ["매출유형"]
    assert {r.value for r in map_sales_table(tables[0], 2025)} >= {147041, 165021}


def test_numbered_sales_subheading_variants():
    for h in ("가. 매출", "가. 매출에 관한 사항", "가. 매출사항", "4.1. 매출 개요", "1) 매출",
              "가-1. 주요 매출 등의 현황", "(1) 매출 상황", "가. 매출 및 수주상황"):
        assert _is_sales_heading(h), h


def test_non_sales_short_texts_are_not_headings():
    for h in ("라. 주요매출처", "2.7 매출채권", "매출", "매출액", "26. 매출액", "나. 판매경로",
              "4.2. 주요 매출처", "(2) 수주상황", "4. 매출 및 수주상황"):
        assert not _is_sales_heading(h), h


def test_subheading_window_found():
    root = _doc('<TITLE>4. 매출 및 수주상황</TITLE><SPAN>가. 매출에 관한 사항</SPAN>'
                f'{_SALES_TABLE}<SPAN>나. 수주방법 및 수주전략</SPAN>')
    assert _heads(root) == ["매출유형"]


def test_table_straight_under_section_title():
    root = _doc(f'<TITLE>4. 매출 및 수주상황</TITLE><SPAN>(단위: 천원, %)</SPAN>{_SALES_TABLE}'
                '<P>나. 판매경로 및 판매방법 등</P>'
                '<TABLE><TBODY><TR><TD>부서명</TD><TD>주요 영업내용</TD></TR>'
                '<TR><TD>국내사업</TD><TD>영업</TD></TR></TBODY></TABLE>')
    assert _heads(root) == ["매출유형"]


def test_window_ends_at_next_title():
    root = _doc(f'<TITLE>4. 매출 및 수주상황</TITLE>{_SALES_TABLE}'
                f'<TITLE>5. 위험관리 및 파생거래</TITLE>{_RND_TABLE}')
    assert _heads(root) == ["매출유형"]


def test_old_style_heading_window_also_ends_at_title():
    # Pre-R352 a "가. 매출실적" window ran on into the next section's tables.
    root = _doc(f'<SPAN>가. 매출실적</SPAN>{_UNIT}{_SALES_TABLE}'
                f'<TITLE>5. 위험관리 및 파생거래</TITLE>{_RND_TABLE}')
    assert _heads(root) == ["매출유형"]


def test_title_and_subheading_windows_do_not_duplicate():
    root = _doc('<TITLE>4. 매출 및 수주상황</TITLE><P>가. 매출실적</P>'
                f'{_SALES_TABLE}<P>나. 판매경로</P>')
    assert _heads(root) == ["매출유형"]


def test_other_titles_are_not_markers():
    root = _doc(f'<TITLE>9. 매출채권 및 기타채권</TITLE>{_SALES_TABLE}'
                f'<TITLE>26. 매출액과 매출원가</TITLE>{_SALES_TABLE}')
    assert _heads(root) == []


def test_order_tables_are_not_claimed_customer_tables_are():
    # Order tables are left for the order-backlog / catalog readers (A/B 2026-11-19: 285 catalog
    # order tables had been hidden). Customer sales tables stay sales (the catalog misses most).
    root = _doc(f'<TITLE>4. 매출 및 수주상황</TITLE>{_SALES_TABLE}'
                '<TABLE><TBODY><TR><TD>구분</TD><TD>발주처</TD><TD>공사명</TD><TD>계약잔액</TD></TR>'
                '<TR><TD>국내</TD><TD>A</TD><TD>B</TD><TD>1,000</TD></TR></TBODY></TABLE>'
                '<TABLE><TBODY><TR><TD>주요매출처</TD><TD>매출액</TD></TR>'
                '<TR><TD>A사</TD><TD>2,000</TD></TR></TBODY></TABLE>')
    assert _heads(root) == ["매출유형", "주요매출처"]
