"""R247 — a bare `6개월`/`9개월`/`12개월` column header in an interim 2-level header is the cumulative column.

이랜시스 20191107000097 separate IS: header [3개월 | 9개월] has no `누적` word, so the 3-month value
(24,622,000) was stored as the current cumulative instead of the printed 9-month 61,884,385.
"""
from pathlib import Path

import pytest

from fin2.extract.text import _CUM_RE
from parser.xml.table_extractor import _SUBTYPE_CUM_RE

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSDAQ" / "01199189_이랜시스" / "quarter" / "2019" / "20191107000097.xml"


@pytest.mark.parametrize("rx", [_CUM_RE, _SUBTYPE_CUM_RE])
@pytest.mark.parametrize("text", ["9개월", "6 개월", "12개월", "누적", "누 적", "누계"])
def test_cumulative_headers(rx, text):
    assert rx.search(text)


@pytest.mark.parametrize("rx", [_CUM_RE, _SUBTYPE_CUM_RE])
@pytest.mark.parametrize("text", ["3개월", "13개월", "19개월"])
def test_not_cumulative(rx, text):
    assert not rx.search(text)


@pytest.mark.skipif(not RAW.exists(), reason="raw report not available")
def test_ielsis_q3_takes_nine_month_column():
    from fin2.extract.report_lines import extract_report_lines
    lines = extract_report_lines(RAW, rcept_no="20191107000097", corp_code="01199189",
                                 report_fiscal_year=2019, report_fiscal_period="Q3")
    got = {l.label_raw: l.value_won for l in lines if l.statement == "IS" and l.basis == "separate" and l.col_index == 0}
    assert got["판매비와관리비"] == 61884385 and got["금융수익"] == 135932245
