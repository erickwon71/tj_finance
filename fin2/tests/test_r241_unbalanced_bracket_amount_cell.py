"""R241 — an amount cell with only one bracket ('7,526,247)') is an unreadable printed value.

`parse_amount` returns None for it, so the cell vanished without a trace (알체라 20210323001167
BS 기타포괄손익누계액 당기). Like the R160 '.'-broken cell it now keeps its place with a NULL value
and the printed text in value_raw; nothing is guessed (R0-2, R6).
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import _emit_section_lines  # noqa: E402
from parser.xml.table_extractor import unresolved_dot_cell_indices  # noqa: E402

_TABLE = """<TABLE><TBODY>
<TR><TD>과목</TD><TD>제5기</TD><TD>제4기</TD><TD>제3기</TD></TR>
<TR><TD>자본금</TD><TD>1,000</TD><TD>1,000</TD><TD>1,000</TD></TR>
<TR><TD>기타포괄손익누계액</TD><TD>7,526,247)</TD><TD>45,034</TD><TD>(888,621)</TD></TR>
</TBODY></TABLE>"""


def test_one_sided_brackets_are_unresolved_cells():
    assert unresolved_dot_cell_indices(["7,526,247)", "(7,526,247", "[1,234", "1,234]"], "x") == [0, 1, 2, 3]


def test_balanced_cells_footnote_marks_and_plain_numbers_are_not():
    assert unresolved_dot_cell_indices(["(7,526,247)", "1)", "(1", "12,345", "-", "[1,234]"], "x") == []


def test_row_keeps_the_cell_as_null_with_printed_text():
    out: list = []
    _emit_section_lines(
        "BS_C", [(etree.fromstring(_TABLE), 1, None)], emit=out.append,
        corp_code="T", rcept_no="R241-0000000001", report_fiscal_year=2020,
        report_fiscal_period="FY", doc_default_unit=(None, None), section_unit_cache={})
    cells = {(l.col_index): (l.value_won, l.value_raw) for l in out if l.label_raw == "기타포괄손익누계액"}
    assert cells[0] == (None, "7,526,247)")
    assert cells[1][0] == 45034 and cells[2][0] == -888621
