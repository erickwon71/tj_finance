"""
account_mapper 세전이익(EBT) 가드 회귀 테스트 (DB 비의존).

배경(Gate B fail_b 트리아지, 2026-06-18): '법인세비용차감전이익(손실)' 같은 세전이익(EBT)
라벨이 '법인세비용' 부분문자열 때문에 퍼지로 is.tax_expense 로 오매핑 → _collect max-abs 가
거대한 세전이익을 tax_expense 로 채택(동성화인텍 등 111사 2,665셀). 가드로 '차감전' 라벨은
is.ebt(중단영업은 무매핑)로 귀속, 진짜 법인세비용은 그대로 tax_expense.

실행: python fin2/tests/test_account_mapper_ebt.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_pretax_variants_map_to_ebt_not_tax():
    m = get_mapper()
    for lbl in (
        "법인세비용차감전이익(손실)",        # exact 미등록 → 이전엔 tax 로 오매핑되던 핵심 케이스
        "법인세비용차감전손실",
        "법인세비용(혜택) 차감전순이익(손실)",
        "법인세비용차감전(손실)",
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.ebt", f"{lbl} -> {r.account_code}"


def test_real_tax_still_maps_to_tax():
    m = get_mapper()
    for lbl in ("법인세비용", "법인세비용(수익)", "법인세비용(이익)", "법인세"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.tax_expense", f"{lbl} -> {r.account_code}"


def test_discontinued_pretax_not_tax_nor_ebt():
    # 중단영업 세전손익 = 총 EBT 아님 → 무매핑(raw 보존), tax/ebt 비오염.
    m = get_mapper()
    for lbl in ("법인세비용차감전중단영업순이익(손실)", "법인세비용차감전중단영업순손실"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_exact_ebt_aliases_unaffected():
    m = get_mapper()
    for lbl in ("법인세비용차감전순이익", "법인세비용차감전계속영업이익"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.ebt", f"{lbl} -> {r.account_code}"


def test_guard_is_section_scoped():
    # CF 섹션에서는 가드 미발동(indirect-method 시작라인은 CF 표준계정 아님 → 무매핑).
    m = get_mapper()
    r = m.map("법인세비용차감전이익(손실)", fs_section="cf")
    assert r.account_code != "is.ebt", r.account_code


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
