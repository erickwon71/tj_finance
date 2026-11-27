"""R399 - '(1) 요약재무상태표 -' inside the notes zone is a note sub-title, not a statement heading.

Tovis 20140530001276 (2014Q1): the merger note's summary BS tables were read as separate BS table_seq 0 and 2.
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl
from fin2.extract.text import _R399_PAREN_NUM_SUMMARY_RE

RAW = Path(__file__).resolve().parents[1] / "raw_report"


@pytest.mark.parametrize("text,ok", [("(1)요약재무상태표-", True), ("（2）요약손익계산서", True),
                                      ("재무상태표", False), ("(1)재무상태표", False)])
def test_regex(text, ok):
    assert bool(_R399_PAREN_NUM_SUMMARY_RE.match(text)) is ok


def test_tovis_separate_bs_only_statement_table():
    files = [f for m in ("KOSPI", "KOSDAQ") if (RAW / m).exists() for d in (RAW / m).iterdir()
             for f in glob.glob(str(d / "quarter" / "2014" / "20140530001276.xml"))]
    if not files:
        pytest.skip("original XML is not on disk")
    ls = rl.extract_report_lines(files[0], rcept_no="20140530001276", corp_code=files[0].split("/")[-4].split("_")[0],
                                 report_fiscal_year=2014, report_fiscal_period="Q1")
    sep = [l for l in ls if l.statement == "BS" and l.basis == "separate"]
    assert {l.table_seq for l in sep} == {0}
    assert 871083 not in {l.value_won for l in sep}
