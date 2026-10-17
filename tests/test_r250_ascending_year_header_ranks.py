"""R250 — year headers printed oldest-first (2015년 | 2016년 | 2017년) still rank the newest as current.

에브리봇 20180402004986 (2017FY): the leftmost 2015 column was loaded as the current period.
"""
from pathlib import Path

import pytest

from parser.xml.table_extractor import _columns_from_grid

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSDAQ" / "01201590_에브리봇" / "annual" / "2017" / "20180402004986.xml"


def _ranks(headers):
    cols = _columns_from_grid([["과 목"] + headers])
    return [c.period_rank for c in cols]


def test_ascending_years_are_reversed():
    assert _ranks(["2015년", "2016년", "2017년"]) == [2, 1, 0]


def test_descending_years_unchanged():
    assert _ranks(["2017년", "2016년", "2015년"]) == [0, 1, 2]


def test_ordinal_keys_left_alone():
    assert _ranks(["제1기", "제2기", "제3기"]) == [0, 1, 2]


@pytest.mark.skipif(not RAW.exists(), reason="raw report not available")
def test_everybot_current_period_is_2017():
    from fin2.extract.report_lines import extract_report_lines
    lines = extract_report_lines(RAW, rcept_no="20180402004986", corp_code="01201590",
                                 report_fiscal_year=2017, report_fiscal_period="FY")
    cur = [l.value_won for l in lines if l.statement == "BS" and l.basis == "separate"
           and l.col_index == 0 and "자산총계" in l.label_raw]
    assert cur == [5546712403]
