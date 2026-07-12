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

_BASE = Path(__file__).resolve().parents[2]
_SAMSUNG = _BASE / "raw_report/KOSPI/00126380_삼성전자/annual/2025/20260310002820.xml"
_HYUNDAI = _BASE / "raw_report/KOSPI/00164742_현대자동차/annual/2025/20260318001394.xml"
_LGCHEM = _BASE / "raw_report/KOSPI/00356361_LG화학/annual/2025/20260313001195.xml"
_SOIL = _BASE / "raw_report/KOSPI/00138279_S-Oil/annual/2025/20260320000559.xml"

_MM = 1_000_000  # 백만원 → 원


def _codes(fp, cc, rev):
    facts = extract_expense_nature_facts(
        fp, rcept_no="X", corp_code=cc, report_fiscal_year=2025,
        report_fiscal_period="FY", basis="consolidated", revenue_ref=rev)
    return {f.canonical_account: f.amount_won for f in facts}


def test_samsung_separate_dep_amo():
    """감가상각비/무형자산상각비 분리 라인 → dep+amo+da_total 정확(성격별 비용 그룹열 무시)."""
    d = _codes(_SAMSUNG, "00126380", 333_605_938 * _MM)
    assert d.get("note.depreciation") == 43_605_740 * _MM, d.get("note.depreciation")
    assert d.get("note.amortization") == 3_320_852 * _MM, d.get("note.amortization")
    assert d.get("note.da_total") == (43_605_740 + 3_320_852) * _MM
    # 비용성격 상세도 함께 방출.
    assert d.get("note.raw_materials_used") == 102_992_621 * _MM
    assert d.get("note.employee_benefits") == 37_094_712 * _MM


def test_hyundai_separate_dep_amo():
    d = _codes(_HYUNDAI, "00164742", 186_254_472 * _MM)
    assert d.get("note.depreciation") == 3_744_754 * _MM, d.get("note.depreciation")
    assert d.get("note.amortization") == 1_271_730 * _MM
    assert d.get("note.da_total") == (3_744_754 + 1_271_730) * _MM


def test_lgchem_combined_da_line():
    """'감가상각비, 무형자산상각비' 결합 라인 → da_total 직접, dep/amo 미분리(NULL)."""
    d = _codes(_LGCHEM, "00356361", 45_932_167 * _MM)
    assert d.get("note.da_total") == 5_247_870 * _MM, d.get("note.da_total")
    assert "note.depreciation" not in d and "note.amortization" not in d, d


def test_soil_combined_da_line():
    d = _codes(_SOIL, "00138279", 34_246_957 * _MM)
    assert d.get("note.da_total") == 720_944 * _MM, d.get("note.da_total")


def test_da_over_revenue_guard_sane():
    """모든 표본의 da_total/revenue 가 현실 범위(0.1~60%)."""
    for fp, cc, rev in ((_SAMSUNG, "00126380", 333_605_938 * _MM),
                        (_HYUNDAI, "00164742", 186_254_472 * _MM),
                        (_LGCHEM, "00356361", 45_932_167 * _MM),
                        (_SOIL, "00138279", 34_246_957 * _MM)):
        if not fp.exists():
            continue
        d = _codes(fp, cc, rev)
        da = d.get("note.da_total")
        assert da and 0.001 <= da / rev <= 0.6, (cc, da, rev)


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
