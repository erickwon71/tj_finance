"""R386 / R387 / R388 - statement headings the legacy walker refused (missing_row batch #290).

R386  '1) 분기연결재무상태표' (numbered sub-heading before the notes) - 삼성물산 20141031002167
R387  '- ... 이익잉여금처분계산서(안) 참조 <현 금 흐 름 표>' (remark + heading in one element) - 현대해상 20150331003987
R388  '가. 재무상태표 (은행)' (bank-account suffix; the trust account '(신탁)' stays refused) - 제주은행 20140515001479
"""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl
from fin2.extract.statement_titles import (
    classify_legacy_statement_heading as legacy, classify_statement_in_body_section as body)

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_r386_numbered_heading_only_when_allowed():
    assert legacy("1) 분기연결재무상태표", include_sce=True) is None
    assert legacy("1) 분기연결재무상태표", include_sce=True, allow_numbered=True) == ("consolidated", "BS")
    assert legacy("2) 분기별도현금흐름표", include_sce=True, allow_numbered=True) == ("separate", "CF")


@pytest.mark.parametrize("title", [
    "29. 현금흐름표",                                  # dotted number stays a note heading
    "1) 연결재무상태표의 주요 항목은 다음과 같습니다",    # followed by prose
    "1) 현금및현금성자산",
])
def test_r386_notes_stay_refused(title):
    assert legacy(title, include_sce=True, allow_numbered=True) is None


def test_r387_bracket_tail_after_appropriation_remark():
    t = "- 최근 2사업연도의 배당에 관한 사항 : 이익잉여금처분계산서(안) 참조 <현 금 흐 름 표>"
    assert body(t, include_sce=True) == "CF"
    assert body("< 이 익 잉 여 금 처 분 계 산 서(안)>", include_sce=True) is None
    assert body("이익잉여금처분계산서(안) 참조", include_sce=True) is None


def test_r388_bank_suffix():
    assert legacy("가. 재무상태표 (은행)", include_sce=True) == ("separate", "BS")
    assert legacy("다. 포괄손익계산서 (은행)", include_sce=True) == ("separate", "IS")
    assert legacy("나. 재무상태표 (신탁)", include_sce=True) is None
    assert legacy("라. 포괄손익계산서(신탁)", include_sce=True) is None


def _extract(path_glob, rcept, corp, fy, period):
    g = glob.glob(str(ROOT / path_glob / f"{rcept}.xml"))
    if not g:
        pytest.skip("source XML is not on disk")
    return rl.extract_report_lines(Path(g[0]), rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=period)


@pytest.mark.parametrize("path_glob,rcept,corp,fy,period", [
    ("KOSPI/00149655_*/quarter/2014", "20141031002167", "00149655", 2014, "Q3"),
    ("KOSPI/00148832_*/quarter/2014", "20140515001479", "00148832", 2014, "Q1"),
    ("KOSPI/00164973_*/annual/2014", "20150331003987", "00164973", 2014, "FY"),
])
def test_statements_are_read(path_glob, rcept, corp, fy, period):
    lines = _extract(path_glob, rcept, corp, fy, period)
    got = {(l.statement, l.basis) for l in lines}
    for stmt in ("BS", "IS", "CF", "SCE"):
        assert (stmt, "consolidated") in got
        assert (stmt, "separate") in got
