"""
PRD 01a 결산월 변경 라벨링 — 순수 함수 단위테스트 (DB 불요).
실행: python -m fin2.tests.test_fiscal_relabel
"""
from datetime import date

from collector.filing_collector import (
    _build_fye_timeline,
    _governing_annual,
    _period_end_from_nm,
    _stub_end_dates,
    compute_fiscal_year_period,
)

# 삼성증권 류 전환 timeline: 3월결산 …→ 2013.12 stub(9개월) → 12월결산
TL = _build_fye_timeline([
    (date(2012, 3, 31), 3), (date(2013, 3, 31), 3),
    (date(2013, 12, 31), 12), (date(2014, 12, 31), 12),
])


def test_period_end_from_nm():
    assert _period_end_from_nm("사업보고서 (2013.03)") == (2013, 3, date(2013, 3, 31))
    assert _period_end_from_nm("[기재정정]반기보고서 (2013.09)") == (2013, 9, date(2013, 9, 30))
    assert _period_end_from_nm("분기보고서") is None
    assert _period_end_from_nm("이상 (2013.13)") is None  # 잘못된 월
    print("✓ _period_end_from_nm")


def test_stub_detection():
    # 2013.03→2013.12 간격 9개월 → stub. 나머지 12개월 정상.
    assert _stub_end_dates(TL) == {date(2013, 12, 31)}
    print("✓ _stub_end_dates")


def test_governing_annual():
    # stub 내 interim(2013.06)은 2013.12 가 닫음(fye=12)
    assert _governing_annual(date(2013, 6, 30), TL) == (date(2013, 12, 31), 12)
    # 3월결산기 interim(2012.09)은 2013.03 이 닫음(fye=3)
    assert _governing_annual(date(2012, 9, 30), TL) == (date(2013, 3, 31), 3)
    # 최신 annual 이후 진행중 → 마지막 annual 폴백
    assert _governing_annual(date(2025, 6, 30), TL) == (date(2014, 12, 31), 12)
    print("✓ _governing_annual")


def test_time_aware_label():
    # 3월결산 H1(기말 9월) → 회계연도=결산이 끝나는 해(2013), H1
    assert compute_fiscal_year_period("half", 2012, 9, 3) == (2013, "H1")
    # stub Q1(기말 6월, fye=12) → 2013 Q1
    assert compute_fiscal_year_period("quarter", 2013, 6, 12) == (2013, "Q1")
    # 정상연도 annual(2013.03, fye=3) 과 stub annual(2013.12, fye=12) 둘 다 fy=2013 FY
    assert compute_fiscal_year_period("annual", 2013, 3, 3) == (2013, "FY")
    assert compute_fiscal_year_period("annual", 2013, 12, 12) == (2013, "FY")
    # 12월결산 무회귀: 기존과 동일
    assert compute_fiscal_year_period("quarter", 2020, 3, 12) == (2020, "Q1")
    assert compute_fiscal_year_period("annual", 2020, 12, 12) == (2020, "FY")
    print("✓ compute_fiscal_year_period (time-aware)")


if __name__ == "__main__":
    test_period_end_from_nm()
    test_stub_detection()
    test_governing_annual()
    test_time_aware_label()
    print("\n모든 테스트 통과 (4)")
