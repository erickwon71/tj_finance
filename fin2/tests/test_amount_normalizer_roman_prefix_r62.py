"""`normalize_account_name` 로마숫자 접두어 혼합표기(ASCII+유니코드) 회귀 테스트 (DB 비의존).

배경(R62, 2026-09-02, std_v3 상류결함① 원인규명 중 발견): 유니코드 로마숫자 한 글자
(예 'Ⅲ')는 실제로는 여러 자리('III')를 나타내는데, 옛 코드는 ASCII 전용 정규식과 유니코드
전용 정규식을 **따로** 돌렸다 — 'XⅢ.'(ASCII 'X' + 유니코드 'Ⅲ') 처럼 DART 필자가 섞어 쓰면
유니코드 정규식은 맨 앞이 ASCII라 매치 실패, ASCII 정규식은 'X' 한 글자만 로마숫자로 인식해
지우고 뒤의 'Ⅲ.'을 그대로 남긴다 — 'Ⅲ. 총당기순이익' 같은 잔재가 alias 매칭에 실패해
net_income 결측으로 이어졌다(fin2/tests/test_account_mapper_net_income_paren_variants_r62.py
참고). 수정: 선두 로마숫자류 구간의 유니코드 문자만 ASCII 다중문자로 치환한 뒤 기존 ASCII
문법 정규식 하나로 통일.

실행: python fin2/tests/test_amount_normalizer_roman_prefix_r62.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.amount_normalizer import normalize_account_name  # noqa: E402


def test_mixed_ascii_unicode_roman_prefix_stripped():
    """★핵심 회귀 — 'XⅢ.'류 혼합표기가 통짜로 벗겨진다(수정 전엔 'Ⅲ.'이 잔류했다)."""
    cases = {
        "XⅢ. 총당기순이익": "총당기순이익",
        "XⅢ.총당기순이익(손실)": "총당기순이익(손실)",
        "XⅡ.당기순이익(손실)": "당기순이익(손실)",
        "XⅢ.총당기순이익(Net Income-Total)": "총당기순이익(Net Income-Total)",
    }
    for raw, expected in cases.items():
        got = normalize_account_name(raw)
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


def test_pure_unicode_and_pure_ascii_prefixes_still_work():
    """순수 유니코드('ⅩⅢ.')·순수 ASCII('XIII.') 접두어는 종전대로 정상 동작."""
    cases = {
        "ⅩⅢ. 총당기순이익(손실)": "총당기순이익(손실)",
        "ⅩⅢ.총당기순이익(손실)": "총당기순이익(손실)",
        "XIII. 총당기순이익": "총당기순이익",
        "Ⅰ.유동자산": "유동자산",
        "I. 유동자산": "유동자산",
    }
    for raw, expected in cases.items():
        got = normalize_account_name(raw)
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


def test_non_roman_labels_unaffected():
    """로마숫자 접두어가 아예 없는 라벨은 이 수정으로 건드리지 않는다(무손실 불변식)."""
    cases = {
        "현금및현금성자산": "현금및현금성자산",
        "1. 유동자산": "유동자산",  # 숫자+점 접두어 규칙(별도)이 계속 처리
        "매출액": "매출액",
    }
    for raw, expected in cases.items():
        got = normalize_account_name(raw)
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


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
