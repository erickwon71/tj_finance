"""R377 — FY2014 quarter/half statements with [detail, subtotal] two-cell period groups read the cumulative group.

삼성생명 20141114001086 consolidated IS: the header prints 3개월(2 cells) | 누적(2 cells) under 제59(당)기 3분기.
With the R125 gate closed for FY2014 the header grid read failed and the position fallback loaded the 3-month group
(6,641,942 instead of the printed cumulative 20,337,364).
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI"


def _extract(pattern, rcept, corp, fy, fp):
    files = glob.glob(str(RAW / pattern))
    if not files:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(files[0], rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=fp)


def test_gate_starts_at_fy2014():
    assert rl._DUPLICATE_SUBTYPE_MIN_FY == 2014


def test_r377_samsung_life_q3_reads_cumulative_group():
    lines = _extract("00126256_*/quarter/2014/20141114001086.xml", "20141114001086", "00126256", 2014, "Q3")
    cur = {l.label_raw: l.value_won for l in lines
           if l.statement == "IS" and l.basis == "consolidated" and l.col_index == 0 and l.value_won is not None}
    assert cur["Ⅰ.영업수익"] == 20337364000000
    assert cur["1.보험료수익"] == 12919265000000
    assert cur["7.이자비용"] == 42922000000
