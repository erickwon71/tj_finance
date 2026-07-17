"""
Phase 4(PRD 15) '비용의 성격별 분류' 주석 D&A 추출 회귀 테스트(실측 파일, DB 비의존).

실측 4사(2026-07-12, 2025 사업보고서):
  삼성전자(00126380) — 감가상각비 / 무형자산상각비 **분리** 라인(+ '성격별 비용' 그룹열).
  현대자동차(00164742) — 분리 라인(2열 라벨).
  LG화학(00356361)   — '감가상각비, 무형자산상각비' **결합** 라인 → da_total 직접.
  S-Oil(00138279)    — '감가상각비 및 무형자산 상각비' 결합 라인.

실행: python -m fin2.tests.test_expense_nature
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.expense_nature import extract_expense_nature_facts  # noqa: E402
from fin2.standardize.rules import StdContext, run_rules  # noqa: E402

_BASE = Path(__file__).resolve().parents[2]
_SAMSUNG = _BASE / "raw_report/KOSPI/00126380_삼성전자/annual/2025/20260310002820.xml"
_HYUNDAI = _BASE / "raw_report/KOSPI/00164742_현대자동차/annual/2025/20260318001394.xml"
_LGCHEM = _BASE / "raw_report/KOSPI/00356361_LG화학/annual/2025/20260313001195.xml"
_SOIL = _BASE / "raw_report/KOSPI/00138279_S-Oil/annual/2025/20260320000559.xml"

_MM = 1_000_000  # 백만원 → 원


def _codes(fp, cc):
    facts = extract_expense_nature_facts(
        fp, rcept_no="X", corp_code=cc, report_fiscal_year=2025,
        report_fiscal_period="FY", basis="consolidated")
    return {f.canonical_account: f.amount_won for f in facts}


def _std_da(fp, cc):
    """추출 → rules 까지 태워 std_v2 의 da_total 과 applied_rules 를 본다."""
    facts = extract_expense_nature_facts(
        fp, rcept_no="X", corp_code=cc, report_fiscal_year=2025,
        report_fiscal_period="FY", basis="consolidated")
    canon = {f.canonical_account: f.amount_won for f in facts}
    ctx = StdContext(corp_code=cc, fiscal_year=2025, fiscal_period="FY",
                     basis="consolidated", canon=canon)
    run_rules(ctx)
    return ctx


def test_samsung_separate_dep_amo():
    """감가상각비/무형자산상각비 **분리** 라인 → 구성요소만 방출(성격별 비용 그룹열 무시).

    ★ note.da_total 을 **만들지 않는다**(D8, 2026-07-17): 원문에 '합계' 항목이 없는데 코드가
    dep+amo 를 더해 note.da_total 로 넣으면, rule_additive_da 가 그걸 **직접 공시된 합계**로
    믿고 우선 채택해 공시값과 계산값이 DB 에서 구분되지 않는다.
    """
    d = _codes(_SAMSUNG, "00126380")
    assert d.get("note.depreciation") == 43_605_740 * _MM, d.get("note.depreciation")
    assert d.get("note.amortization") == 3_320_852 * _MM, d.get("note.amortization")
    assert "note.da_total" not in d, f"분리 공시인데 합계를 합성했다: {d.get('note.da_total')}"
    # 비용성격 상세도 함께 방출.
    assert d.get("note.raw_materials_used") == 102_992_621 * _MM
    assert d.get("note.employee_benefits") == 37_094_712 * _MM


def test_samsung_da_total_still_derived_transparently():
    """분리 공시여도 std_v2.da_total 값은 그대로 나온다 — 단 **파생임이 기록**된다.

    D8 제거가 커버리지를 깎지 않음을 보장(값 동일, 출처만 정직해짐).
    """
    ctx = _std_da(_SAMSUNG, "00126380")
    assert ctx.col["da_total"] == (43_605_740 + 3_320_852) * _MM, ctx.col["da_total"]
    assert "additive_da" in ctx.applied, ctx.applied


def test_hyundai_separate_dep_amo():
    d = _codes(_HYUNDAI, "00164742")
    assert d.get("note.depreciation") == 3_744_754 * _MM, d.get("note.depreciation")
    assert d.get("note.amortization") == 1_271_730 * _MM
    assert "note.da_total" not in d, d.get("note.da_total")
    ctx = _std_da(_HYUNDAI, "00164742")
    assert ctx.col["da_total"] == (3_744_754 + 1_271_730) * _MM


def test_lgchem_combined_da_line():
    """'감가상각비, 무형자산상각비' **결합** 라인 → 원문에 합계가 실재 → da_total 직접."""
    d = _codes(_LGCHEM, "00356361")
    assert d.get("note.da_total") == 5_247_870 * _MM, d.get("note.da_total")
    assert "note.depreciation" not in d and "note.amortization" not in d, d


def test_soil_combined_da_line():
    d = _codes(_SOIL, "00138279")
    assert d.get("note.da_total") == 720_944 * _MM, d.get("note.da_total")


def test_provenance_recorded():
    """주석 출처·선언단위가 행에 기록된다(추측/원본 구분 가능해야 함)."""
    facts = extract_expense_nature_facts(
        _SAMSUNG, rcept_no="X", corp_code="00126380", report_fiscal_year=2025,
        report_fiscal_period="FY", basis="consolidated")
    assert facts, "삼성 표본 추출 실패"
    for f in facts:
        assert f.section_kind == "연결재무제표주석", f.section_kind
        assert f.unit_source == "declared", f.unit_source


def _run():
    if not _SAMSUNG.exists():
        print(f"  - SKIP: 실측 파일 없음 {_SAMSUNG}")
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
