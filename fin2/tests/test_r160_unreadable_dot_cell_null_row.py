"""R160 (2026-10-12, user decision) — an unresolved '.'-broken amount cell is loaded as a row with
a NULL value and its printed text in value_raw (R0-1 4항), instead of being dropped.

Before: the cell's value was set to None, the column choice skipped it and the row vanished from
layer 2 (verification saw a missing_row). Now the same column choice runs once more with the
unreadable cells marked; a period that got no value in the normal run gets a NULL row. Numbers
already loaded never change.

실행: pytest fin2/tests/test_r160_unreadable_dot_cell_null_row.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fin2.extract import as_printed as AP  # noqa: E402
from fin2.extract.report_lines import _unreadable_markers, extract_report_lines  # noqa: E402
from fin2.verification import machine_compare as mc  # noqa: E402
from parser.xml.table_extractor import RowData  # noqa: E402

_SCE_2015Q3 = ROOT / "raw_report/KOSDAQ"   # resolved below by glob (company folder name)


def test_markers_only_for_unresolved_dot_cells():
    row = RowData(account_name="미수금", amounts=[None, 5, None],
                  raw_amounts=["125.605", "5", ""], header_hint=None, row_order=0)
    amounts, marks = _unreadable_markers(row)
    assert amounts[1] == 5 and amounts[2] is None          # readable / blank cells untouched
    assert list(marks.values()) == ["125.605"] and amounts[0] in marks
    assert row.amounts == [None, 5, None]                  # the row itself is not modified


def test_per_share_rows_get_no_marker():
    row = RowData(account_name="희석주당이익 (단위 : 원)", amounts=[None],
                  raw_amounts=["343.5"], header_hint=None, row_order=0)
    assert _unreadable_markers(row) == ([None], {})


def _first(pattern: str):
    hits = sorted(ROOT.glob(pattern))
    return hits[0] if hits else None


def test_bs_unreadable_cell_becomes_a_null_row(monkeypatch):
    # 20170331000172 (2016FY) BS '8.미수금' printed `125.605` with no intact twin in the row
    path = _first("raw_report/*/*/annual/2016/20170331000172.xml")
    if path is None:
        pytest.skip("raw_report not mounted")
    monkeypatch.delenv(AP.ENV, raising=False)
    from sqlalchemy import text
    from collector.db import get_session
    with get_session() as s:
        corp = s.execute(text("SELECT corp_code FROM filings WHERE rcept_no='20170331000172'")).scalar()
    lines = extract_report_lines(str(path), rcept_no="20170331000172", corp_code=corp,
                                 report_fiscal_year=2016, report_fiscal_period="FY", include_notes=False)
    hit = [l for l in lines if l.statement == "BS" and l.label_raw.strip() == "8.미수금" and l.col_index == 0]
    assert [(l.value_won, l.value_raw) for l in hit] == [(None, "125.605")]


def _xml(tmp_path, body: str) -> str:
    p = tmp_path / "t.xml"
    p.write_text(f"<DOCUMENT><BODY>{body}</BODY></DOCUMENT>", encoding="utf-8")
    return str(p)


def _bs(rows):
    trs = "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows)
    return ('<SECTION-2><TITLE>2. 연결재무제표</TITLE><P>연결 재무상태표</P>'
            f'<TABLE><THEAD><TR><TH>과목</TH><TH>당기</TH></TR></THEAD><TBODY>{trs}</TBODY></TABLE></SECTION-2>')


def _row(order, label, value, raw=None):
    return {"statement": "BS", "basis": "consolidated", "table_seq": 0, "row_order": order,
            "label_raw": label, "col_index": 0, "value_won": value, "is_cumulative": None,
            "value_raw": raw}


def test_machine_compare_null_row_equals_unreadable_source(tmp_path):
    # mc14: DB NULL row (value_raw '125.605') vs a source cell that is not a number -> same
    tables = mc.load_statement_tables(_xml(tmp_path, _bs([["현금", "300"], ["미수금", "125.605"]])))
    rows = [_row(0, "현금", 300), _row(1, "미수금", None, "125.605")]
    res = mc.compare(rows, tables)
    assert not [f for f in res.findings if f["kind"] in ("value", "missing_row", "extra_row")], res.findings


def test_machine_compare_null_row_over_a_readable_number_is_a_finding(tmp_path):
    # mc14: DB NULL where the source prints a readable non-zero number -> value finding
    tables = mc.load_statement_tables(_xml(tmp_path, _bs([["현금", "300"], ["미수금", "125,605"]])))
    rows = [_row(0, "현금", 300), _row(1, "미수금", None, "125.605")]
    res = mc.compare(rows, tables)
    v = [f for f in res.findings if f["kind"] == "value"]
    assert len(v) == 1 and v[0]["db"] is None
