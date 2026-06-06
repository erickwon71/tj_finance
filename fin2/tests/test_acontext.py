"""
acontext.parse_acontext 단위 테스트. 실측 ACONTEXT 문자열(신흥에스이씨 2024 등) 기반.
핵심: 현 파이프라인의 'Consolidated' substring 버그를 멤버 토큰 판정이 막는지 검증.

실행: python -m fin2.tests.test_acontext   (pytest 없어도 동작)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.acontext import parse_acontext  # noqa: E402


def test_consolidated_member():
    c = parse_acontext(
        "CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assert c.parsed
    assert c.basis == "consolidated"
    assert c.col_index == 0 and c.fiscal_year == 2024
    assert c.period_kind == "duration" and c.period_type == "FY"
    assert c.is_cumulative is False
    assert c.extra_dims == []


def test_separate_member_not_misclassified():
    # ★ 버그 재현 케이스: 축 이름에 'Consolidated' 가 들어있지만 멤버는 Separate.
    c = parse_acontext(
        "PFY2023eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    )
    assert c.basis == "separate", "SeparateMember 인데 연결로 오분류되면 안 됨"
    assert c.col_index == 1 and c.fiscal_year == 2023
    assert c.period_kind == "instant"   # eFY = BS 시점
    assert c.extra_dims == []


def test_before_prior_instant():
    c = parse_acontext(
        "BPFY2022eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assert c.col_index == 2 and c.fiscal_year == 2022
    assert c.period_kind == "instant"
    assert c.basis == "consolidated"


def test_sce_extra_dim_excluded():
    # SCE 내역 분해: ComponentsOfEquityAxis 는 extra_dims → 합계 제외 대상
    c = parse_acontext(
        "CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
        "_ifrs-full_ComponentsOfEquityAxis_ifrs-full_RetainedEarningsMember"
    )
    assert c.basis == "consolidated"
    assert c.is_dimensional is True
    assert ("ComponentsOfEquityAxis", "RetainedEarningsMember") in c.extra_dims


def test_dart_member_extra_dim():
    c = parse_acontext(
        "CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
        "_ifrs-full_ComponentsOfEquityAxis_dart_CapitalSurplusMember"
    )
    assert c.basis == "separate"
    assert ("ComponentsOfEquityAxis", "CapitalSurplusMember") in c.extra_dims


def test_revenue_duration_vs_assets_instant():
    rev = parse_acontext(
        "CFY2024dFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assets = parse_acontext(
        "CFY2024eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assert rev.period_kind == "duration"   # IS 흐름
    assert assets.period_kind == "instant"  # BS 시점


def test_cumulative_quarter():
    c = parse_acontext(
        "CFY2026eFQA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assert c.period_type == "FQ" and c.is_cumulative is True
    assert c.period_kind == "instant"


def test_half_year_member():
    # ★ 회귀 버그: 반기(HY)는 F 로 시작하지 않아 구식 정규식이 통째로 탈락시켜
    #   basis/연도 NULL → reconcile 드롭. 이제 파싱돼야 함.
    c = parse_acontext(
        "CFY2025eHYA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    assert c.parsed
    assert c.basis == "consolidated"
    assert c.col_index == 0 and c.fiscal_year == 2025
    assert c.period_kind == "instant"      # e = BS 시점
    assert c.period_type == "FH"           # HY → 반기
    assert c.is_cumulative is True          # A = 누적


def test_third_quarter_discrete_vs_cumulative():
    disc = parse_acontext(
        "CFY2025dTQQ_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    )
    cum = parse_acontext(
        "CFY2025dTQA_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    )
    assert disc.basis == "separate" and cum.basis == "separate"
    assert disc.period_type == "FQ" and cum.period_type == "FQ"  # TQ(3분기) → FQ 도메인
    assert disc.period_kind == "duration"
    assert disc.is_cumulative is False     # Q = 3개월 분기값
    assert cum.is_cumulative is True       # A = 누적(YTD)


def test_half_year_no_suffix_instant():
    c = parse_acontext(
        "CFY2025eHY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    )
    assert c.parsed and c.basis == "separate"
    assert c.period_type == "FH" and c.is_cumulative is False


def test_no_basis_axis_falls_back_none():
    c = parse_acontext("CFY2024dFY")  # 차원 없음
    assert c.parsed and c.basis is None and c.col_index == 0


def test_unparseable_returns_unparsed():
    c = parse_acontext("SOME_LEGACY_FORMAT")
    assert c.parsed is False and c.basis is None


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
