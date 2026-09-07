"""
account_mapper 1글자 차이(뜻은 정반대) 라벨 오매핑 회귀 테스트 (DB 비의존).

배경(DB증권 00115694 155행 전수 원문대조, 2026-09-07): 한국 회계용어는 "차/대"·
"임차/임대"처럼 딱 한 글자 차이로 뜻이 정반대(자산↔부채)가 되는 쌍이 있는데,
그 정확한 짝이 exact alias 로 등록 안 돼 있으면 Jaro-Winkler 퍼지 매칭이 편집거리만
보고 반대쪽(뜻이 다른) alias 에 붙어버린다:

  - "임차보증금"(세입자가 낸 보증금, 자산) → exact alias 없어 "임대보증금"(부채,
    임대인이 받은 보증금)에 오매핑. 실측: DB증권 BS 174억원이 bs.other_noncurrent_
    liabilities 로 잘못 들어감.
  - "이연법인세대"(K-GAAP 구세대 대변=부채 표기) → exact alias 없어 "이연법인세자산"
    (신세대 표기)에 오매핑. 실측: DB증권 BS 2.3억원이 bs.deferred_tax_asset 로
    잘못 들어감(진짜 부채인데 자산으로 잡힘).

두 계정 모두 그랜드토탈(자산총계/부채총계/자본총계) 자체는 각각 별도 라벨로
직접 뽑히므로 이 버그가 항등식 검증 결과를 틀리게 만들진 않았지만, 세부
라인아이템이 계속 오염된 채로 남아있었다. account_maps/bs_accounts.py 에
정확한 exact alias 를 추가해(Stage 1/2 가 Stage 3 퍼지보다 우선) 해소.

실행: python fin2/tests/test_account_mapper_lessee_deposit_and_kgaap_deferred_tax.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_lessee_deposit_maps_to_asset_not_landlord_deposit_liability():
    m = get_mapper()
    r = m.map("임차보증금", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_assets", r.account_code


def test_landlord_deposit_still_maps_to_liability_unaffected():
    # "임대보증금"(부채, 정반대 뜻)의 기존 매핑이 이번 수정으로 안 깨졌는지 확인.
    m = get_mapper()
    r = m.map("임대보증금", fs_section="bs")
    assert r.account_code == "bs.other_noncurrent_liabilities", r.account_code


def test_kgaap_deferred_tax_debit_maps_to_asset():
    m = get_mapper()
    r = m.map("이연법인세차", fs_section="bs")
    assert r.account_code == "bs.deferred_tax_asset", r.account_code


def test_kgaap_deferred_tax_credit_maps_to_liability_not_asset():
    m = get_mapper()
    r = m.map("이연법인세대", fs_section="bs")
    assert r.account_code == "bs.deferred_tax_liability", r.account_code


def test_modern_deferred_tax_labels_still_correct_unaffected():
    m = get_mapper()
    assert m.map("이연법인세자산", fs_section="bs").account_code == "bs.deferred_tax_asset"
    assert m.map("이연법인세부채", fs_section="bs").account_code == "bs.deferred_tax_liability"


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
