"""
Track A XBRL 추출기 회귀 테스트 (실측 파일 기반, DB 비의존).

실측: 신흥에스이씨(00807379) 2024 사업보고서.
핵심 검증:
  - ADECIMAL=0 → 표기값이 이미 원-스케일(현 파이프라인 standard_financials 값과 일치).
  - 연결/별도 멤버 토큰 판정(별도가 연결로 오분류되지 않음).
  - instant(BS)/duration(IS) 구분.
파일이 없으면 스킵(다른 환경에서 안전).

실행: python -m fin2.tests.test_xbrl
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.xbrl import extract_facts  # noqa: E402

_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00807379_신흥에스이씨/annual/2024/20250317000923.xml"
)
_RCEPT = "20250317000923"
_CORP = "00807379"

# 현 파이프라인 standard_financials 와 대조한 권위 값(원 단위, col_index=0 당기)
_EXPECTED = {
    ("ifrs-full_Assets", "consolidated"): 875_737_888_728,
    ("ifrs-full_Revenue", "consolidated"): 432_831_192_104,
    ("ifrs-full_Equity", "consolidated"): 358_403_579_067,
    ("ifrs-full_Assets", "separate"): 534_380_373_372,
    ("ifrs-full_Revenue", "separate"): 170_752_287_902,
    ("ifrs-full_Equity", "separate"): 320_849_482_599,
}


def _extract():
    return extract_facts(
        _SAMPLE, rcept_no=_RCEPT, corp_code=_CORP,
        report_fiscal_year=2024, report_fiscal_period="FY",
    )


def test_won_scale_matches_pipeline():
    facts = _extract()
    current = {
        (f.acode, f.basis): f.amount_won
        for f in facts
        if f.col_index == 0 and not f.is_dimensional
    }
    for key, expected in _EXPECTED.items():
        assert current.get(key) == expected, f"{key}: {current.get(key)} != {expected}"


def test_separate_not_misclassified():
    facts = _extract()
    # 별도 Assets 가 연결 값으로 새지 않아야 함
    sep_assets = [
        f.amount_won for f in facts
        if f.acode == "ifrs-full_Assets" and f.basis == "separate"
        and f.col_index == 0 and not f.is_dimensional
    ]
    assert sep_assets == [534_380_373_372]


def test_instant_vs_duration():
    facts = _extract()
    by = {(f.acode, f.basis, f.col_index): f for f in facts if not f.is_dimensional}
    assert by[("ifrs-full_Assets", "consolidated", 0)].period_kind == "instant"   # BS
    assert by[("ifrs-full_Revenue", "consolidated", 0)].period_kind == "duration"  # IS


def test_dimensional_flag_present():
    facts = _extract()
    # SCE 내역(ComponentsOfEquityAxis 등) 행이 일부 존재하고 합계제외로 표시됨
    assert any(f.is_dimensional for f in facts)


def _run():
    if not _SAMPLE.exists():
        print(f"  - SKIP: 실측 파일 없음 {_SAMPLE}")
        return 0
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
