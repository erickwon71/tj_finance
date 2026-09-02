"""
account_mapper is.net_income '(당기)' 삽입형·'총당기순이익' 계열 회귀 테스트 (DB 비의존).

배경(std_v3 상류결함① 원인규명, 2026-09-02, R62): 현대차 separate 2012~2017Q1/H1 등
interim 행의 net_income 이 NULL 인데 같은 행 ebt/tax_expense 는 정상 존재 —
'분기(당기)순이익' 같은 '(당기)' 삽입형 라벨, 'ⅩⅢ.총당기순이익(손실)' 같은 K-GAAP 구서식
로마숫자 접두 라벨이 기존 alias 목록(정확)·fuzzy(임계 0.88 미달) 둘 다 못 잡아 후보 자체가
비어있었다. 로마숫자 혼합표기(ASCII+유니코드, 'XⅢ.')는 amount_normalizer 쪽 별도 버그도
같이 수정(fin2/tests/test_amount_normalizer_roman_prefix_r62.py 참고).

실행: python fin2/tests/test_account_mapper_net_income_paren_variants_r62.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_paren_insertion_variants_map_to_net_income():
    m = get_mapper()
    for lbl in (
        "분기(당기)순이익",
        "반기(당기)순이익",
        "당(분)기순이익(손실)",
        "당(반)기순이익(손실)",
        "당기(전기)순이익(손실)",
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.net_income", f"{lbl} -> {r.account_code}"


def test_total_net_income_kgaap_variants_map_to_net_income():
    m = get_mapper()
    for lbl in (
        "총당기순이익",
        "총당기순이익(손실)",
        "총당기순이익(Net Income-Total)",
        # 로마숫자 접두(순수 유니코드/순수 ASCII/혼합) — normalize_account_name 이 벗겨낸 뒤 매치
        "ⅩⅢ.총당기순이익(손실)",
        "XIII. 총당기순이익",
        "XⅢ. 총당기순이익",
        "XⅢ.당기순이익(손실)",
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code == "is.net_income", f"{lbl} -> {r.account_code}"


def test_continuing_operations_income_not_registered():
    # IFRS '계속영업이익(손실)'은 중단영업 제외분 — 있으면 net_income 보다 작다(00102113
    # 2024FY 실측: 계속영업 -5,678,950,649 vs 실제 net_income 1,315,633,234). 등록하면
    # 중단영업이 있는 문서에서 net_income 오염 → 의도적으로 무매핑 유지.
    m = get_mapper()
    r = m.map("계속영업이익(손실)", fs_section="is")
    assert r.account_code != "is.net_income", r.account_code


def test_unrelated_totals_not_pulled_into_net_income():
    # 항등식(ebt-tax) 우연 일치로 오혼동되기 쉬운 이웃 개념들 — 각자 제 canonical 로.
    m = get_mapper()
    assert m.map("총포괄손익", fs_section="is").account_code == "is.total_comprehensive_income"
    assert m.map("법인세비용차감전순이익(손실)", fs_section="is").account_code == "is.ebt"


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
