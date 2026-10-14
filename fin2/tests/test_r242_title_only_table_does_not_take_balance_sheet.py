"""R242 - a title-only IS/CF table must not take a balance-sheet table as its data.

The title/data split branch of `_detect_body_statement_tables` links the first data table after a
title-only table. A footnote sentence that names a statement ('※ 연결 손익계산서, 연결 포괄손익계산서
원화 환산시 적용환율은 …') is classified as a title, so the next data table - a balance sheet - was
stored under CF_C (두산밥캣 20260514001068 and 5 sibling filings, 52 BS rows in the consolidated CF).
This is the balance-sheet twin of R127b.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.text import _detect_body_statement_tables  # noqa: E402

_PER = "제 13 기 1분기 2026.01.01 부터 2026.03.31 까지"


def _title(text: str) -> str:
    return f"<TABLE><TR><TD><P>{text}</P></TD></TR></TABLE>"


# a neutral one-row table keeps the data table from inheriting the title as its own heading,
# so it takes the title/data split branch (the layout of 두산밥캣 20260514001068)
_SPACER = _title("환율")

_BS = ("<TABLE><TR><TD><P>자산</P></TD><TD><P>금액</P></TD></TR>"
       "<TR><TD><P>자산총계</P></TD><TD><P>12,220,859</P></TD></TR>"
       "<TR><TD><P>자본총계</P></TD><TD><P>453,861</P></TD></TR></TABLE>")
_CF = ("<TABLE><TR><TD><P>구분</P></TD><TD><P>금액</P></TD></TR>"
       "<TR><TD><P>영업활동으로 인한 현금흐름</P></TD><TD><P>170,749</P></TD></TR>"
       "<TR><TD><P>투자활동으로 인한 현금흐름</P></TD><TD><P>(20,000)</P></TD></TR></TABLE>")


def _doc(body: str):
    return etree.fromstring(f"<DOCUMENT><SECTION-2><TITLE>2. 연결재무제표</TITLE>{body}</SECTION-2></DOCUMENT>")


def _cf_rows(root) -> list[str]:
    groups = _detect_body_statement_tables(root, "A", include_sce=True)
    return [" ".join("".join(t.itertext()).split())[:40] for t, _, _ in groups.get("CF_C", [])]


def test_cf_title_does_not_attach_a_balance_sheet_as_its_data():
    root = _doc(_title("2-5. 연결 현금흐름표") + _SPACER + _BS)
    cf = _cf_rows(root)
    assert cf == [], cf


def test_is_title_does_not_attach_a_balance_sheet_as_its_data():
    root = _doc(_title("2-2. 연결 손익계산서") + _SPACER + _BS)
    groups = _detect_body_statement_tables(root, "A", include_sce=True)
    assert groups.get("IS_C", []) == []


def test_cf_title_skips_the_balance_sheet_and_finds_the_real_cash_flow():
    root = _doc(_title("2-5. 연결 현금흐름표") + _SPACER + _BS + _CF)
    cf = _cf_rows(root)
    assert len(cf) == 1 and "영업활동" in cf[0], cf


def test_real_cash_flow_after_a_title_is_still_found():
    root = _doc(_title("2-5. 연결 현금흐름표") + _CF)
    cf = _cf_rows(root)
    assert len(cf) == 1 and "영업활동" in cf[0], cf
