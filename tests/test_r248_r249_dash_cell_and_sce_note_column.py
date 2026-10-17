"""R248 — a printed dash in the current amount column is a real (blank) cell, not a phantom slot.
R249 — an SCE column headed 주석 holds note numbers, not amounts.

안트로젠 20150513001760 separate CF `유형자산의 처분`: cells [note '', current '-', prior '4,000,000'] — the
dash was trimmed as a phantom leading cell, so the prior-period 4,000,000 was stored as the current value.
나인테크 20190329000201 separate SCE `전환사채의 자본요소`: the 주석 column value `8` was stored as an amount.
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSDAQ"


def test_dash_is_not_a_phantom_leading_cell():
    assert "-" not in rl._LEAD_TRIM_PLACEHOLDERS and "" in rl._LEAD_TRIM_PLACEHOLDERS


@pytest.mark.parametrize("label,expected", [("주석", True), ("주 석", True), ("주석번호", True), ("자본금", False),
                                            (None, False), ("", False)])
def test_note_ref_column_label(label, expected):
    assert rl._is_note_ref_column_label(label) is expected


def _extract(pattern, rcept, corp, fy, fp):
    files = glob.glob(str(RAW / pattern))
    if not files:
        pytest.skip("raw report not available")
    return rl.extract_report_lines(Path(files[0]), rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=fp)


def test_antrogen_current_dash_does_not_take_prior_value():
    lines = _extract("00631837_*/quarter/2015/20150513001760.xml", "20150513001760", "00631837", 2015, "Q1")
    rows = [l for l in lines if l.statement == "CF" and l.basis == "separate" and "유형자산의 처분" in l.label_raw]
    assert [(l.col_index, l.value_won) for l in rows if l.value_won is not None] == [(1, 4000000)]


def test_nine_tech_sce_note_number_is_not_an_amount():
    lines = _extract("*_*/annual/2018/20190329000201.xml", "20190329000201", "00000000", 2018, "FY")
    sce = [l for l in lines if l.statement == "SCE" and l.basis == "separate" and "전환사채의 자본요소" in l.label_raw]
    assert sce and all((l.col_label or "").replace(" ", "") != "주석" for l in sce)
