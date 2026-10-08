"""R226 — H1/Q3 XBRL SCE cells whose only fact is the single-quarter context are not stored."""
from __future__ import annotations

from datetime import date

from parser.xbrl_instance.instance_parser import XbrlContext

import fin2.extract.report_lines_xbrl as X


def _ctx(start: str, end: str) -> XbrlContext:
    return XbrlContext(id="c", entity_cik=None, period_kind="duration", start_date=start, end_date=end)


CUM = _ctx("2015-01-01", "2015-09-30")
QTR = _ctx("2015-07-01", "2015-09-30")
OPENING = date(2015, 1, 1)


def test_quarter_only_fact_dropped_in_q3_and_h1():
    assert X._is_quarter_only_sce_cell(QTR, OPENING, "Q3")
    assert X._is_quarter_only_sce_cell(_ctx("2019-04-01", "2019-06-30"), date(2019, 1, 1), "H1")


def test_cumulative_fact_kept():
    assert not X._is_quarter_only_sce_cell(CUM, OPENING, "Q3")


def test_q1_and_fy_untouched():
    # Q1: the 3-month and the cumulative context cover the same dates (이엔플러스 20190516000238).
    q1 = _ctx("2018-01-01", "2018-03-31")
    assert not X._is_quarter_only_sce_cell(q1, date(2018, 1, 1), "Q1")
    assert not X._is_quarter_only_sce_cell(QTR, OPENING, "FY")


def test_instant_or_unknown_opening_untouched():
    inst = XbrlContext(id="i", entity_cik=None, period_kind="instant", instant="2015-09-30")
    assert not X._is_quarter_only_sce_cell(inst, OPENING, "Q3")
    assert not X._is_quarter_only_sce_cell(QTR, None, "Q3")
