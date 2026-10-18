"""R254 - statement title recognition gaps found by the missing_row review (batch 166 defer).

KD 20200515002825 (`연결 재무상태표` merged title), 기업은행 20200515002364 (`(1) 은행계정` sub-heading),
한화생명 20150515001946 (`포괄계산서`), 에이비온 20160330003188 (`제7(전전) 기` period lines),
아바텍 20231114002605 (bare `자본변동` section title).
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

from fin2.extract import statement_titles as st

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _tbl(first_row):
    return etree.fromstring(f"<TABLE><TBODY><TR><TD>{first_row}</TD></TR><TR><TD>자산</TD><TD>1</TD></TR></TBODY></TABLE>")


def test_merged_title_with_basis_prefix():
    assert st.owned_merged_title(_tbl("연결 재무상태표")) == "BS"
    assert st.owned_merged_title(_tbl("별도 현금흐름표")) == "CF"
    assert st.owned_merged_title(_tbl("재무상태표")) == "BS"
    assert st.owned_merged_title(_tbl("연결 주석")) is None


def test_comprehensive_statement_name_variant():
    assert st.classify_statement_in_body_section("나. 포괄계산서") == "IS"


def test_bare_sce_section_title():
    assert st.classify_statement_in_body_section("자본변동", include_sce=True) == "SCE"
    assert st.classify_statement_in_body_section("자본변동", include_sce=False) is None
    assert st.classify_statement_in_body_section("주석 자본변동 내역") is None


def _siblings(*parts):
    xml = "<SEC>" + "".join(parts) + "<TABLE><TBODY><TR><TD>과목</TD><TD>1</TD></TR><TR><TD>매출</TD><TD>5</TD></TR></TBODY></TABLE></SEC>"
    root = etree.fromstring(xml)
    return root.findall("TABLE")[-1]


def test_bank_account_subtitle_is_skipped_but_trust_account_is_not():
    bank = _siblings("<P>분 기 포 괄 손 익 계 산 서</P>", "<P>(1) 은행계정</P>")
    assert st.classify_statement_in_body_section(st.title_text_for_classify(bank)) == "IS"
    trust = _siblings("<P>분 기 포 괄 손 익 계 산 서</P>", "<P>(2)신탁계정</P>")
    assert st.classify_statement_in_body_section(st.title_text_for_classify(trust)) is None


def test_period_lines_with_parenthesized_ordinal_are_metadata():
    tbl = _siblings("<P>손익계산서</P>", "<P>(단위: 원)</P>", "<P>제7(전전) 기 2013년 01월 01일부터 2013년 12월 31일</P>",
                    "<P>제 8(전) 기 2014년 01월 01일부터 2014년 12월 31일</P>", "<P>제 9(당) 기 2015년 01월 01일부터 2015년 12월 31일</P>")
    assert st.classify_statement_in_body_section(st.title_text_for_classify(tbl)) == "IS"


def _lines(rel, rcept, corp, fy, fp):
    from fin2.extract.report_lines import extract_report_lines
    path = ROOT / rel
    if not path.exists():
        pytest.skip("raw report not available")
    return extract_report_lines(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                report_fiscal_period=fp, include_notes=False)


@pytest.mark.parametrize("rel,rcept,corp,fy,fp,basis,stmt", [
    ("KOSDAQ/00111218_KD/quarter/2020/20200515002825.xml", "20200515002825", "00111218", 2020, "Q1", "consolidated", "BS"),
    ("KOSPI/00149646_기업은행/quarter/2020/20200515002364.xml", "20200515002364", "00149646", 2020, "Q1", "separate", "IS"),
    ("KOSPI/00113058_한화생명/quarter/2015/20150515001946.xml", "20150515001946", "00113058", 2015, "Q1", "separate", "IS"),
    ("KOSDAQ/00977377_에이비온/annual/2015/20160330003188.xml", "20160330003188", "00977377", 2015, "FY", "separate", "IS"),
    ("KOSDAQ/00442048_아바텍/quarter/2023/20231114002605.xml", "20231114002605", "00442048", 2023, "Q3", "separate", "SCE"),
])
def test_target_filings_load_the_statement(rel, rcept, corp, fy, fp, basis, stmt):
    got = [l for l in _lines(rel, rcept, corp, fy, fp) if l.basis == basis and l.statement == stmt and l.col_index == 0]
    assert len(got) >= 4
