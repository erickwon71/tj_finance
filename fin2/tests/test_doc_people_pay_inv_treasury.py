"""API→문서 전환 Phase 3~6 매퍼 — grids from 삼양식품 사업보고서 as stored by layer 2."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.doc_common import money_unit, parse_years
from fin2.layer3.doc_investments import map_investments
from fin2.layer3.doc_pay import map_pay_individuals, map_pay_summary
from fin2.layer3.doc_people import map_employees, map_executives
from fin2.layer3.doc_treasury import map_treasury

_EMP = [
    ["직원"] * 10 + ["소속 외근로자"] * 3 + ["비고"],
    ["사업부문", "성별"] + ["직 원 수"] * 5 + ["평 균근속연수", "연간급여총 액", "1인평균급여액", "남", "여", "계", "비고"],
    ["사업부문", "성별", "기간의 정함이없는 근로자", "기간의 정함이없는 근로자", "기간제근로자",
     "기간제근로자", "합 계", "평 균근속연수", "연간급여총 액", "1인평균급여액", "남", "여", "계", "비고"],
    ["사업부문", "성별", "전체", "(단시간근로자)", "전체", "(단시간근로자)", "합 계", "평 균근속연수",
     "연간급여총 액", "1인평균급여액", "남", "여", "계", "비고"],
    ["식품(영업/관리)", "남", "527", "-", "33", "-", "560", "6년 5개월", "38,149,069", "68,123",
     "198", "62", "260", "-"],
    ["합 계", "합 계", "1,945", "-", "445", "-", "2,390", "5년 5개월", "129,634,197", "54,240",
     "198", "62", "260", "-"],
]


def test_money_unit_from_caption():
    assert money_unit([[["(기준일 :", "2024년 12월 31일", ")", "(단위 : 천원)"]], _EMP]) == 1000
    assert money_unit([[["(단위 : 천원, 주, %)"]]]) == 1000
    assert money_unit([[["(기준일 :", "2024년 12월 31일", ")", "(단위 : 주)"]]]) is None


def test_parse_years():
    assert parse_years("6년 5개월") == 6.42
    assert parse_years("5개월") == 0.42
    assert parse_years("7.3") == 7.3
    assert parse_years("-") is None


def test_employees_four_header_rows_and_total_skipped():
    rows = map_employees(_EMP, 1000)
    assert rows == [{"division": "식품(영업/관리)", "sex": "남", "regular_count": 527,
                     "contract_count": 33, "total_count": 560, "avg_tenure_years": 6.42,
                     "annual_salary_total": 38149069000, "avg_salary": 68123000, "remark": "-"}]


def test_employees_no_unit_no_amount():
    assert map_employees(_EMP, None)[0]["annual_salary_total"] is None


def test_executives_registered_and_fulltime_from_text():
    grid = [
        ["성명", "성별", "출생년월", "직위", "등기임원여부", "상근여부", "담당업무", "주요경력",
         "소유주식수", "소유주식수", "최대주주와의관계", "재직기간", "임기만료일"],
        ["성명", "성별", "출생년월", "직위", "등기임원여부", "상근여부", "담당업무", "주요경력",
         "의결권있는 주식", "의결권없는 주식", "최대주주와의관계", "재직기간", "임기만료일"],
        ["김정수", "여", "1964년 03월", "부회장", "사내이사", "상근", "경영총괄", "학사",
         "325,850", "-", "특수관계인", "2020.10~", "2027년 03월 28일"],
        ["김명진", "여", "1977년 11월", "예우임원", "미등기", "비상근", "자문역", "-", "-", "-",
         "해당없음", "2020.12~", "-"],
    ]
    a, b = map_executives(grid)
    assert (a["is_registered"], a["is_fulltime"], a["tenure_end"]) == (True, True, "2027년 03월 28일")
    assert (b["is_registered"], b["is_fulltime"]) == (False, False)


def test_pay_summary_and_individuals_in_won():
    s = map_pay_summary([["인원수", "보수총액", "1인당 평균보수액", "비고"],
                         ["8", "3,131,790", "391,474", "-"]], 1000)
    assert s == {"total_exec_count": 8, "total_pay_amount": 3131790000,
                 "avg_pay_per_person": 391474000, "remark": None}
    ind = map_pay_individuals([["이름", "직위", "보수총액", "보수총액에 포함되지 않는 보수"],
                               ["김정수", "부회장", "1,876,518", "-"]], 1000)
    assert [(r["person_name"], r["total_pay_amount"]) for r in ind] == [("김정수", 1876518000)]


def test_investments_three_level_header_dates_and_total():
    grid = [
        ["법인명", "상장여부", "최초취득일자", "출자목적", "최초취득금액", "기초잔액", "기초잔액",
         "기초잔액", "증가(감소)", "증가(감소)", "증가(감소)", "기말잔액", "기말잔액", "기말잔액",
         "최근사업연도재무현황", "최근사업연도재무현황"],
        ["법인명", "상장여부", "최초취득일자", "출자목적", "최초취득금액", "수량", "지분율",
         "장부가액", "취득(처분)", "취득(처분)", "평가손익", "수량", "지분율", "장부가액", "총자산",
         "당기순손익"],
        ["법인명", "상장여부", "최초취득일자", "출자목적", "최초취득금액", "수량", "지분율",
         "장부가액", "수량", "금액", "평가손익", "수량", "지분율", "장부가액", "총자산", "당기순손익"],
        ["SAMYANG AMERICA, INC.", "비상장", "2021년 08월 25일", "경영참여", "1,000", "10", "100.00",
         "1,000", "-", "-", "-", "10", "100.00", "1,000", "5,000", "-200"],
        ["합 계", "합 계", "합 계", "합 계", "합 계", "10", "-", "1,000", "-", "-", "-", "10", "-",
         "1,000", "5,000", "-200"],
    ]
    a, t = map_investments(grid, 1000)
    assert a["first_acquired_date"] == "2021.08.25" and a["end_book_value"] == 1000000
    assert a["investee_net_income"] == -200000 and a["end_pct"] == 100.0
    assert t["investee_name"] == "합계" and t["purpose"] is None


def test_treasury_keeps_source_labels_and_order():
    grid = [
        ["취득방법", "취득방법", "취득방법", "주식의 종류", "기초수량", "변동 수량", "변동 수량",
         "변동 수량", "기말수량", "비고"],
        ["취득방법", "취득방법", "취득방법", "주식의 종류", "기초수량", "취득(+)", "처분(-)",
         "소각(-)", "기말수량", "비고"],
        ["기타 취득(c)", "기타 취득(c)", "기타 취득(c)", "보통주", "407", "1", "-", "-", "408", "-"],
        ["총 계(a+b+c)", "총 계(a+b+c)", "총 계(a+b+c)", "-", "407", "1", "-", "-", "408", "-"],
    ]
    a, t = map_treasury(grid)
    assert (a["acqs_method1"], a["qty_begin"], a["qty_acquired"], a["qty_end"]) == \
        ("기타 취득(c)", 407, 1, 408)
    assert t["stock_kind"] is None and t["remark"] is None


def test_pay_summary_2015_form_from_breakdown_total_row():
    from fin2.layer3.doc_pay import map_pay_summary_from_breakdown
    grid = [["구 분", "인원수", "보수총액", "1인당 평균보수액", "비고"],
            ["등기이사", "5", "740", "12", "-"],
            ["사외이사", "2", "48", "2", "-"],
            ["계", "8", "824", "-", "-"]]
    assert map_pay_summary_from_breakdown(grid, 1_000_000) == {
        "total_exec_count": 8, "total_pay_amount": 824000000, "avg_pay_per_person": None,
        "remark": None}


def test_employees_single_division_named_jeonche_is_kept():
    grid = [_EMP[1][:10], _EMP[2][:10], _EMP[3][:10],
            ["전체", "남", "43", "-", "-", "-", "43", "6.8", "1,725", "40"],
            ["합 계", "합 계", "50", "-", "-", "-", "50", "6.2", "1,963", "39"]]
    rows = map_employees(grid, 1_000_000)
    assert [(r["division"], r["sex"], r["total_count"]) for r in rows] == [("전체", "남", 43)]
