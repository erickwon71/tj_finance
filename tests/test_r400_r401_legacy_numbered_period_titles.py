"""R400 / R401 - statement headings the legacy walker refused (missing_row batch, 2026-11-28).

R400  '1. 분기재무상태표' / '1. 재무상태표' (period-numbered title before the notes) - 한국캐피탈, 에프앤가이드
R401  '재 무 상 태 표 제 15(당) 1분기 2014년 ...' (quarter number between the term and the date) - AJ네트웍스
"""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl
from fin2.extract.statement_titles import classify_legacy_statement_heading as legacy

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
SD = Path("/Volumes/dart_data/raw_report")


def test_r400_dotted_number_only_when_allowed():
    assert legacy("1. 분기재무상태표", include_sce=True, allow_numbered=True) is None
    assert legacy("1. 분기재무상태표", include_sce=True, allow_numbered=True,
                  allow_numbered_dot=True) == ("separate", "BS")
    assert legacy("2.분기포괄손익계산서", include_sce=True, allow_numbered=True,
                  allow_numbered_dot=True) == ("separate", "IS")
    assert legacy("3. 반기자본변동표", include_sce=True, allow_numbered=True,
                  allow_numbered_dot=True) == ("separate", "SCE")
    assert legacy("1. 재무상태표", include_sce=True, allow_numbered=True,
                  allow_numbered_dot=True) == ("separate", "BS")


@pytest.mark.parametrize("title", [
    "5. 대손충당금 설정현황",
    "1. 현금및예치금",
    "29. 현금흐름표의 현금은 다음과 같습니다",         # prose after the name
    "1. 연결재무제표에 대한 주석",
])
def test_r400_other_numbered_items_stay_refused(title):
    assert legacy(title, include_sce=True, allow_numbered=True, allow_numbered_dot=True) is None


def test_r400_roman_numbered_stays_refused():
    assert legacy("Ⅲ. 재무상태표", include_sce=True, allow_numbered=True,
                  allow_numbered_dot=True) is None


def test_r401_quarter_number_after_term():
    t = ("손 익 계 산 서 제 15(당) 1분기 2014년 1월 1일부터 2014년 03월 31일까지 "
         "제 14(전) 1분기 2013년 1월 1일부터 2013년 03월 31일까지")
    assert legacy(t, include_sce=True, allow_numbered=True) == ("separate", "IS")
    t3 = "현 금 흐 름 표 제 15(당) 3분기 2014년 1월 1일부터 2014년 09월 30일까지"
    assert legacy(t3, include_sce=True, allow_numbered=True) == ("separate", "CF")


def _source(path_glob, rcept):
    for base in (ROOT, SD):
        g = glob.glob(str(base / path_glob / f"{rcept}.xml"))
        if g:
            return Path(g[0])
    pytest.skip("source XML is not on disk")


@pytest.mark.parametrize("path_glob,rcept,corp,fy,period,expect", [
    ("KOSDAQ/00149594_*/quarter/2014", "20141114000214", "00149594", 2014, "Q3", {"BS", "IS", "SCE", "CF"}),
    ("KOSDAQ/00149594_*/quarter/2014", "20140515000175", "00149594", 2014, "Q1", {"BS", "IS", "SCE", "CF"}),
    ("KOSDAQ/00149594_*/half/2014", "20140814000737", "00149594", 2014, "H1", {"BS", "IS", "SCE", "CF"}),
    ("KOSDAQ/00331016_*/half/2014", "20140814000071", "00331016", 2014, "H1", {"BS", "IS", "CF"}),
    ("KOSPI/00365387_*/quarter/2014", "20140515000263", "00365387", 2014, "Q1", {"BS", "IS", "SCE", "CF"}),
])
def test_r400_r401_filings_read_all_statements(path_glob, rcept, corp, fy, period, expect):
    lines = rl.extract_report_lines(_source(path_glob, rcept), rcept_no=rcept, corp_code=corp,
                                    report_fiscal_year=fy, report_fiscal_period=period)
    got = {l.statement for l in lines if l.basis == "separate"}
    assert expect <= got
