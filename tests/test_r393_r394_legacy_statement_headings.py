"""R393 / R394 - legacy statement headings that the classifier used to reject.

R393: `자 본 변 동 표 제 10(당) 2014년 1월 1일부터 ...` (term number + (당)/(전) + date, no `기`) -
      Jeju Air 20141114000458 / 20140814001033 lost the separate SCE and CF.
R394: `2. 별 도재무정보 (K-IFRS)가. 재무상태표` (section heading `재무정보`, title glued to it) -
      Itcen Global 20131129002001 lost the separate BS.
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl
from fin2.extract.statement_titles import classify_legacy_statement_heading as classify

RAW = Path(__file__).resolve().parents[1] / "raw_report"


@pytest.mark.parametrize("text,expected", [
    ("자 본 변 동 표 제 10(당) 2014년 1월 1일부터 2014년 9월 30일까지 제 9(전) 2013년 1월 1일부터 2013년 9월 30일까지 (단위: 원)",
     ("separate", "SCE")),
    ("현 금 흐 름 표 제 10(당) 2014년 1월 1일부터 2014년 9월 30일까지 제 9(전) 2013년 1월 1일부터 2013년 9월 30일까지 (단위: 원)",
     ("separate", "CF")),
    ("2. 별 도재무정보 (K-IFRS)가. 재무상태표", ("separate", "BS")),
    ("2. 별 도재무정보가. 반기재무상태표", ("separate", "BS")),
    ("1. 연결재무정보 가. 재무상태표", ("consolidated", "BS")),
    ("1. 연결재무정보 가. 연결재무상태표", ("consolidated", "BS")),
])
def test_headings_are_recognized(text, expected):
    assert classify(text, True) == expected


@pytest.mark.parametrize("text", [
    "29. 재무상태표",
    "2. 별도재무정보에 대한 설명 가. 현금흐름표는 다음과 같다",
    "현금흐름표는 제 10(당) 2014년 현금을 의미합니다",
])
def test_note_like_text_is_still_rejected(text):
    assert classify(text, True) is None


def _lines(market, pref, sub, year, rcept, corp, fy, fp):
    base = RAW / market
    dirs = [d for d in (base.iterdir() if base.exists() else []) if d.name.startswith(pref)]
    files = [f for d in dirs for f in glob.glob(str(d / sub / year / f"{rcept}.xml"))]
    if not files:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(files[0], rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=fp)


@pytest.mark.parametrize("rcept,sub,fp", [("20141114000458", "quarter", "Q3"), ("20140814001033", "half", "H1")])
def test_jeju_air_separate_sce_and_cf_loaded(rcept, sub, fp):
    ls = _lines("KOSPI", "00555874", sub, "2014", rcept, "00555874", 2014, fp)
    assert {"SCE", "CF"} <= {l.statement for l in ls if l.basis == "separate"}


def test_itcen_separate_bs_loaded():
    ls = _lines("KOSDAQ", "00620868", "half", "2013", "20131129002001", "00620868", 2013, "H1")
    vals = {l.value_won for l in ls if l.statement == "BS" and l.basis == "separate"}
    assert 27204157620 in vals
