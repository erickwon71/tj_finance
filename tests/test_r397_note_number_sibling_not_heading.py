"""R397 - a note title whose number sits in its own SPAN ('22.' + '현금흐름표') is not a statement heading.

MK Electron 20140530000903 (2014Q1): the consolidated note '22. 현금흐름표' read as a bare separate CF heading,
so the consolidated adjustment table landed in the separate CF (value mismatch #572938-#572942, extra rows #572943-#572944).
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

from fin2.extract import report_lines as rl
from fin2.extract.text import _preceded_by_number_only_sibling

RAW = Path(__file__).resolve().parents[1] / "raw_report"


def _spans(first):
    root = etree.fromstring(f"<P><SPAN>{first}</SPAN><SPAN>현금흐름표</SPAN></P>")
    return root[1]


@pytest.mark.parametrize("first,expected", [("22. ", True), ("3)", True), ("가. ", False), ("주석 22. ", False)])
def test_number_only_sibling(first, expected):
    assert _preceded_by_number_only_sibling(_spans(first)) is expected


def test_mk_electron_separate_cf_has_only_statement_table():
    files = [f for m in ("KOSPI", "KOSDAQ") if (RAW / m).exists() for d in (RAW / m).iterdir()
             if d.name.startswith("00121686") for f in glob.glob(str(d / "quarter" / "2014" / "20140530000903.xml"))]
    if not files:
        pytest.skip("original XML is not on disk")
    ls = rl.extract_report_lines(files[0], rcept_no="20140530000903", corp_code="00121686",
                                 report_fiscal_year=2014, report_fiscal_period="Q1")
    sep = [l for l in ls if l.statement == "CF" and l.basis == "separate"]
    assert {l.table_seq for l in sep} == {0}
    assert 880149000 not in {l.value_won for l in sep}
