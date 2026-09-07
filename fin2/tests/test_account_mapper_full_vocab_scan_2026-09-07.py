"""account_mapper 전체 어휘 스캔(형태소 반의어 갭)으로 찾은 2건 회귀 테스트.

배경(2026-09-07, DB증권 155행 원문대조 후속 — 사용자 지시 "전체 어휘 스캔을
별도 진행해봐"): 등록된 818개 alias 전체에 회계 반의어 쌍(채권/채무, 취득/처분
등)을 적용해 미등록 변형이 fuzzy 로 어디에 붙는지 전수 확인.

1) "비유동기타채무"(부채) — 어순만 뒤집힌 "기타비유동채무"는 이미 등록돼
   있는데 이 변형은 없어서 자산쪽 "비유동기타채권"에 오매핑되던 갭 → exact
   alias 추가로 해결.
2) CF/NOTE 의 "취득"(canonical 있음) ↔ "처분"(canonical 자체가 없음) 반의어
   6종 — 정확한 반대쪽 canonical 이 아예 없어 alias 로는 못 고치므로,
   `_FUZZY_BLOCK` 에 등록해 부호가 반대인 취득 계정으로 오매핑되는 대신
   무매핑(unknown)으로 떨어지게 방어(결측이 오염보다 낫다). 전용 처분 canonical
   신설(스키마 확장)은 이번 스코프 밖 — 별도 결정 필요.

실행: python fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_reordered_other_noncurrent_payables_maps_to_liability_not_asset():
    m = get_mapper()
    r = m.map("비유동기타채무", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_liabilities", r.account_code


def test_original_word_order_still_correct_unaffected():
    m = get_mapper()
    r = m.map("기타비유동채무", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_liabilities", r.account_code


def test_disposal_side_labels_blocked_not_flipped_into_acquisition_code():
    """전용 '처분' canonical 이 없는 6개 라벨 — 부호 반대인 '취득' 코드로
    오매핑되는 대신 무매핑(unknown)으로 떨어져야 한다."""
    m = get_mapper()
    cases = [
        ("종속기업의처분", "cf"),
        ("관계기업의처분", "cf"),
        ("공동기업투자의처분", "cf"),
        ("공동기업의처분", "cf"),
        ("투자부동산의취득", "cf"),
        ("기계장치의취득", "cf"),
        ("차량운반구의취득", "cf"),
        ("산업재산권의처분", "cf"),
        ("자기주식의처분", "cf"),
        ("자기주식처분금액", "note"),
    ]
    for lbl, sec in cases:
        r = m.map(lbl, fs_section=sec)
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code} (부호반대 오염 위험)"


def test_acquisition_side_labels_still_correctly_mapped_unaffected():
    m = get_mapper()
    assert m.map("종속기업의취득", fs_section="cf").account_code == "cf.acquisition_of_subsidiaries"
    assert m.map("관계기업의취득", fs_section="cf").account_code == "cf.acquisition_of_associates"
    assert m.map("자기주식의취득", fs_section="cf").account_code == "cf.treasury_stock_purchase"
    assert m.map("투자부동산의처분", fs_section="cf").account_code == "cf.investment_property_proceeds"


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
