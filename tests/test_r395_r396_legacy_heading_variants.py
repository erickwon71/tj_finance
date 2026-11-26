"""R395 / R396 - more legacy statement-heading variants the walk used to lose.

R395: a statement title glued after the previous note sentence (`...참조하시기 바랍니다.2. 재무제표 가. 재 무 상 태 표`);
      the R101 tail fragment kept its section number and was rejected (Eugene Investment 20141114000770 separate BS).
R396: (a) spans nested in the heading <P> aged the pending heading out before the data table (E*Trade Securities
      20140515001537 / 20140520000172 separate CF); (b) the bare heading `2. 재무제표` (no `등`) with a period table
      and no BS title (Eugene Investment 20140515001231 separate BS).
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl
from fin2.extract.statement_titles import classify_legacy_statement_heading as classify

RAW = Path(__file__).resolve().parents[1] / "raw_report"


@pytest.mark.parametrize("text,expected", [
    ("주2) 참조하시기 바랍니다.2. 재무제표 가. 재 무 상 태 표", ("separate", "BS")),
    ("주1) 수치입니다.1. 연결재무제표 가. 연결재무상태표", ("consolidated", "BS")),
    ("주1) 수치입니다.1. 연결재무제표 가. 재무상태표", ("consolidated", "BS")),
])
def test_glued_title_after_sentence(text, expected):
    assert classify(text, True) == expected


@pytest.mark.parametrize("text", ["2. 재무제표 가. 재무상태표 상 부채는 다음과 같다.", "29. 재무상태표"])
def test_note_like_still_rejected(text):
    assert classify(text, True) is None


def _lines(market, pref, sub, year, rcept, corp, fy, fp):
    dirs = [d for m in ("KOSPI", "KOSDAQ") for d in ((RAW / m).iterdir() if (RAW / m).exists() else [])
            if d.name.startswith(pref)]
    files = [f for d in dirs for f in glob.glob(str(d / sub / year / f"{rcept}.xml"))]
    if not files:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(files[0], rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=fp)


def _has(ls, stmt, basis, value):
    return value in {l.value_won for l in ls if l.statement == stmt and l.basis == basis}


def test_glued_title_separate_bs():
    ls = _lines("KOSPI", "", "quarter", "2014", "20141114000770", "", 2014, "Q3")
    assert _has(ls, "BS", "separate", 71529912723)


def test_nested_span_heading_separate_cf():
    ls = _lines("KOSPI", "", "quarter", "2014", "20140515001537", "", 2014, "Q1")
    assert any(l.statement == "CF" and l.basis == "separate" for l in ls)


def test_bare_fs_heading_separate_bs():
    ls = _lines("KOSPI", "", "quarter", "2014", "20140515001231", "", 2014, "Q1")
    assert _has(ls, "BS", "separate", 78552614624)
