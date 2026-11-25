"""R391 - `FY2014 3분기` / `FY2013` English-prefixed period headers are period keys.

Yuanta Securities 20141114000904: the THEAD prints `FY2014 3분기` | ` FY2013` with 3개월 | 누적 sub-columns.
Without a key for `FY2013` the header grid read failed, the position fallback took the 3-month cell as current
(240,453,442) and the cumulative cell as the prior year, instead of the printed cumulative 591,872,109.
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl
from parser.xml.table_extractor import _PERIOD_KEY_RE

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI"


def test_fy_prefixed_headers_are_period_keys():
    assert _PERIOD_KEY_RE.search("FY2014 3분기").group(0).startswith("FY2014")
    assert _PERIOD_KEY_RE.search(" FY2013").group(0) == "FY2013"


def test_yuanta_q3_reads_cumulative_group():
    files = glob.glob(str(RAW / "00117601_*/quarter/2014/20141114000904.xml"))
    if not files:
        pytest.skip("original XML is not on disk")
    lines = rl.extract_report_lines(files[0], rcept_no="20141114000904", corp_code="00117601",
                                    report_fiscal_year=2014, report_fiscal_period="Q3")
    cur = {l.col_index: l.value_won for l in lines
           if l.statement == "IS" and l.basis == "consolidated" and l.label_raw.startswith("Ⅰ. 영업수익")}
    assert cur[0] == 591872109000
    assert cur[1] == 1078866134000
