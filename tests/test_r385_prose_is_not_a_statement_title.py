"""R385 - a paragraph that merely mentions a statement name is not the table's title.

형지엘리트 20150129000055, 동원모빌리티 20150226000480, KG파이낸셜 20170112000195/20170207000223: the
receivable-ageing note table under '당사는 재무상태표일 현재 …' was read as a second separate balance sheet.
"""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl
from fin2.extract.statement_titles import statement_name_followed_by_prose as prose

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


@pytest.mark.parametrize("title", [
    "연결 재무상태표 제33기 반기말 2015년 6월 30일 현재 (단위 : 원)",
    "재무상태표 제 14 기 1분기말 2014년 9월 30일 현재",
    "나. 연결손익계산서(포괄손익계산서)",
    "주) 당반기말 연결재무상태표는 소급재작성되지 아니함 나. 연결손익계산서(포괄손익계산서)",
    "재무상태표",
    "제 13 기 3분기말 현금흐름표 (단위: 백만원)",
    "4. 연결재무제표 (1) 연결 재무상태표 (제 49 기 : 2014. 12. 31 현재)",
])
def test_headings_are_not_prose(title):
    assert prose(title) is False


@pytest.mark.parametrize("title", [
    "다. 매출채권관련 대손충당금 설정방침 당사는 재무상태표일 현재의 매출채권과 기타채권 잔액에 대하여 합리적이고 객관 적인 기준에 따라 산출한 대손추산액을 대손충당금으로 설정하고 있습니다.",
    "당사는 재무상태표일 현재 매출채권 등의 잔액에 대하여 거래처별 개별분석과 과거의 대손경험을 토대로 예상되는 대손추정액중 큰 금액을 대손충당금으로 설정하고 있습니다. 1) 거래처별 개별분석에 의한 대손추산액 재무상태표일 현재 매출채권과 기타채권에 대하여 아래와 같은 기준에 따라 거 래처별",
])
def test_sentences_are_prose(title):
    assert prose(title) is True


def _extract(corp_dir, sub, rcept, corp, fy, period, market="KOSPI"):
    g = glob.glob(str(ROOT / market / corp_dir / sub / f"{rcept}.viewer.xml"))
    if not g:
        pytest.skip("web-view print is not on disk")
    return rl.extract_report_lines(Path(g[0]), rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=period)


@pytest.mark.parametrize("corp_dir,sub,rcept,corp,fy,period,market", [
    ("00441243_*", "quarter/2015", "20150129000055", "00441243", 2015, "Q1", "KOSPI"),
    ("00118008_*", "quarter/2015", "20150226000480", "00118008", 2015, "Q3", "KOSPI"),
    ("00405278_*", "quarter/2014", "20170112000195", "00405278", 2014, "Q3", "KOSDAQ"),
    ("00405278_*", "quarter/2014", "20170207000223", "00405278", 2014, "Q3", "KOSDAQ"),
])
def test_ageing_note_table_is_not_a_second_separate_bs(corp_dir, sub, rcept, corp, fy, period, market):
    lines = _extract(corp_dir, sub, rcept, corp, fy, period, market)
    assert {l.table_seq for l in lines if l.statement == "BS" and l.basis == "separate"} == {0}
    assert any(l.statement == "BS" and l.basis == "separate" and l.label_raw == "자산총계" for l in lines)
