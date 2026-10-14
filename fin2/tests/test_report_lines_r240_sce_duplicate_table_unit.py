"""R240 — one SCE table listed twice with different units: the first entry used to win.

The body-table detector can list the same data table twice (title-table branch and the table's
own heading). `_emit_sce_lines` took the first entry's unit (1) even when the table's own
declaration said 백만원, so a whole 연결 자본변동표 was stored unscaled (IBK 20160816001912 and
its correction 20160825000311: 자본금 3,255,948 instead of 3,255,948,000,000).
The sibling emitter for BS/IS/CF was not affected.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import _emit_sce_lines  # noqa: E402

_DOC = """<BODY>
<P>중소기업은행과 그 종속기업 (단위 : 백만원)</P>
<TABLE><TBODY>
<TR><TD>과 목</TD><TD>자본금</TD><TD>자본잉여금</TD><TD>이익잉여금</TD><TD>총 계</TD></TR>
<TR><TD>2015.1.1(전기초)</TD><TD>3,255,948</TD><TD>507,976</TD><TD>10,456,352</TD><TD>14,220,276</TD></TR>
</TBODY></TABLE>
</BODY>"""


def _run(units: list[int | None]):
    root = etree.fromstring(_DOC)
    table = root.find("TABLE")
    out: list = []
    _emit_sce_lines(
        "SCE_C", [(table, u, None) for u in units], emit=out.append,
        corp_code="TESTCORP", rcept_no="R240-0000000001",
        report_fiscal_year=2016, report_fiscal_period="H1",
        doc_default_unit=(None, None), section_unit_cache={})
    return out


def _capital(rows):
    return [l.value_won for l in rows if l.col_label and l.col_label.endswith("자본금")]


def test_table_own_declaration_wins_over_a_wrong_first_entry():
    assert _capital(_run([1, 1_000_000])) == [3_255_948_000_000]


def test_order_of_the_duplicate_entries_does_not_matter():
    assert _capital(_run([1_000_000, 1])) == [3_255_948_000_000]


def test_single_entry_is_unchanged():
    assert _capital(_run([1_000_000])) == [3_255_948_000_000]
    assert _capital(_run([1_000])) == [3_255_948_000]
