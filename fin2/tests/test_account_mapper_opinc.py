"""
account_mapper 영업이익(is.operating_income) 오매핑 가드 회귀 테스트 (DB 비의존).

배경(C5 크로스소스 검증, 2026-07-06): '계속영업이익(손실)'·'중단영업이익(손실)'(세후 계속/중단
영업 손익 소계, 순이익에 인접한 개념)과 '영업외손익' 계열(영업외수익-비용 순액)이 alias
'영업이익(손실)'/'영업손익' 과의 부분포함·근접 유사도로 Stage 3 퍼지에 오매핑되어(신뢰도
0.9~0.97), build.py max-abs 선택 시 진짜 영업이익을 가리고 부호까지 뒤집는 사고를 냈다
(금호타이어 2022 연결: DART +23.1B vs DB -107.2B 등). DART API 크로스소스로 65건 발견,
그중 operating_income 이 29건으로 압도적 — 이 가드가 그 근본원인을 차단한다.

실행: python fin2/tests/test_account_mapper_opinc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_continuing_discontinued_ops_unmapped():
    m = get_mapper()
    for lbl in (
        "계속영업이익(손실)", "중단영업이익(손실)", "계속영업이익", "중단영업이익",
        "중단영업손익", "계속영업손익", "계속영업순이익(손실)",
        "기본주당계속영업이익(손실)", "희석주당계속영업이익(손실)",  # 주당(EPS) 변형도 동반 차단
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_nonoperating_net_unmapped():
    m = get_mapper()
    for lbl in ("영업외손익", "영업외손익합계", "영업외이익", "영업외이익(손실)",
                "영업외잡이익", "기타영업외이익(손실)"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_real_operating_income_still_maps():
    m = get_mapper()
    for lbl in ("영업이익(손실)", "영업이익", "영업손실", "영업손익", "영업이익 (손실)",
                "총영업이익", "순영업이익"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.operating_income", f"{lbl} -> {r.account_code}"


def test_unrelated_other_income_expense_unaffected():
    # '영업외수익'/'영업외비용'(개별 항목)은 '영업외손익'(순액) 과 다른 개념 — 가드 미발동.
    m = get_mapper()
    assert m.map("영업외수익", fs_section="is").account_code == "is.other_income"
    assert m.map("영업외비용", fs_section="is").account_code == "is.other_expense"


def test_pretax_continuing_ops_guard_still_wins():
    # '차감전'(세전) 계속영업 변형은 EBT 가드가 먼저 처리 — 이 가드로 unknown 되면 안 됨.
    m = get_mapper()
    r = m.map("법인세비용차감전계속영업이익", fs_section="is")
    assert r.account_code == "is.ebt", r.account_code


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
