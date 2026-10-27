"""R116 - a Q1 cumulative column that PRINTS 0 next to a non-zero 3-month value (강원랜드 2017 Q1, consolidated IS).

Q1 cumulative equals the 3-month figure by definition, so the printed 0 is an unfilled placeholder. Only a
listed filing takes the 3-month value; layer 2 keeps the printed 0 (R0-2) and layer 3 gets a 'value' correction.
"""
from pathlib import Path

import pytest

from fin2.extract.report_lines import _Q1_CUM_BLANK_USE_3M_RCEPTS, _Q1_CUM_PRINTED_ZERO_USE_3M_RCEPTS
from parser.xml.table_extractor import HeaderColumn, select_by_header_columns

RCEPT = "20170515004574"
_COLS = [HeaderColumn(position=0, period_key="cur", period_rank=0, subtype="three_month"),
         HeaderColumn(position=1, period_key="cur", period_rank=0, subtype="cumulative")]


def _pick(amounts, **kw):
    return select_by_header_columns(_COLS, amounts, raw_amounts=[str(a) for a in amounts], **kw)


def test_listed_filing_is_in_both_lists():
    assert RCEPT in _Q1_CUM_PRINTED_ZERO_USE_3M_RCEPTS
    assert RCEPT in _Q1_CUM_BLANK_USE_3M_RCEPTS


def test_printed_zero_takes_the_three_month_value_when_flagged():
    assert _pick([422_970_649_918, 0], allow_three_month_as_cumulative=True,
                 zero_cumulative_is_blank=True) == {0: 422_970_649_918}


def test_printed_zero_is_kept_without_the_flag():
    assert _pick([422_970_649_918, 0], allow_three_month_as_cumulative=True) == {0: 0}
    assert _pick([422_970_649_918, 0]) == {0: 0}


def test_both_zero_and_real_cumulative_are_untouched():
    kw = dict(allow_three_month_as_cumulative=True, zero_cumulative_is_blank=True)
    assert _pick([0, 0], **kw) == {0: 0}
    assert _pick([100, 100], **kw) == {0: 100}


_SRC = next(iter(Path("raw_report/KOSPI").glob("00255619_*/quarter/2017/20170515004574.xml")), None) \
    if Path("raw_report/KOSPI").exists() else None


@pytest.mark.skipif(_SRC is None, reason="source file not mounted")
def test_real_filing_layer2_prints_zero_and_layer3_has_three_month_value():
    from fin2.extract.layer3_corrections import extract_xml_with_corrections
    printed, corrections = extract_xml_with_corrections(
        str(_SRC), rcept_no=RCEPT, corp_code="00255619", report_fiscal_year=2017, report_fiscal_period="Q1")
    sales = [l for l in printed if l.statement == "IS" and l.basis == "consolidated"
             and l.label_raw == "매출" and l.col_index == 0]
    assert [l.value_won for l in sales] == [0]
    fixes = [c for c in corrections if c["statement"] == "IS" and c["basis"] == "consolidated"
             and c["label_raw"] == "매출"]
    assert [(c["kind"], c["printed_value"], c["corrected_value"]) for c in fixes] == [
        ("value", 0, 422_970_649_918)]
