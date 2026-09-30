"""R201 — H1/Q3 XBRL cells whose only fact is the single-quarter context are not stored."""
from __future__ import annotations

from parser.xbrl_instance.instance_parser import XbrlContext

import fin2.extract.report_lines_xbrl as X


def _ctx(start: str, end: str) -> XbrlContext:
    return XbrlContext(id="c", entity_cik=None, period_kind="duration", start_date=start, end_date=end)


CUM = _ctx("2017-01-01", "2017-09-30")
QTR = _ctx("2017-07-01", "2017-09-30")


def _cells():
    return [
        ("a", 0, None, CUM, 100),
        ("b", 0, None, QTR, -67431249),   # cumulative cell blank in the filing
        ("c", 1, None, QTR, 5),           # prior column: only the quarter exists there
        ("c", 1, None, CUM, 7),
    ]


def test_quarter_only_cell_dropped_in_q3():
    kept = X._drop_quarter_only_cells(_cells(), "Q3")
    assert [(c[0], c[1]) for c in kept] == [("a", 0), ("c", 1)]
    assert kept[1][3] is CUM


def test_h1_same_as_q3():
    assert len(X._drop_quarter_only_cells(_cells(), "H1")) == 2


def test_q1_and_fy_untouched():
    assert X._drop_quarter_only_cells(_cells(), "Q1") == _cells()
    assert X._drop_quarter_only_cells(_cells(), "FY") == _cells()


# R201-b — machine compare: SCE note ('주석') column offset
def _db(ci, label=None):
    return {"col_index": ci, "col_label": label, "value_won": 1}


def test_sce_note_column_rebased_when_source_dropped_it():
    from fin2.verification.machine_compare import _rebase_sce_note_column
    items = [_db(0, "주석"), _db(1, "자본금"), _db(2, "합계")]
    out = _rebase_sce_note_column(items, True)
    assert [r["col_index"] for r in out] == [0, 1]


def test_sce_rebase_also_when_no_row_carries_a_note_value():
    from fin2.verification.machine_compare import _rebase_sce_note_column
    out = _rebase_sce_note_column([_db(1, "자본금"), _db(3, "합계")], True)
    assert [r["col_index"] for r in out] == [0, 2]


def test_sce_not_rebased_when_source_kept_note_column_as_cell0():
    from fin2.verification.machine_compare import _rebase_sce_note_column
    items = [_db(1, "자본금"), _db(2, "합계")]
    assert _rebase_sce_note_column(items, False) == items
