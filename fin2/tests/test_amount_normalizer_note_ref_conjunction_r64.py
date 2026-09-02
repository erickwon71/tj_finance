"""`normalize_account_name` 주석번호 와/과/및 결합표기 정규화 회귀 테스트 (DB 비의존).

배경(R64, 2026-09-02, R63 후속 후보 착수): 복수 주석번호를 콤마 대신 한글 접속사
("와"/"과"/"및")로 묶는 표기('(주석13과 14)', '(주석1과15)', '(주석5,7과29)' 등)를
구 정규식 `\\(주석?\\s*\\d[\\d,\\s]*\\)`이 못 잡았다 — 숫자 뒤 '과'/'와'/'및'에서 매치가
끊겨 괄호가 안 지워지고 라벨에 그대로 남았다(예: '매출액(주석13과 14)').

실측(KG스틸 00115676, 2006 H1/Q3 별도 IS, R63 CF확장 조사 중 부수발견): 이 라벨
잔재가 짧은 canonical(예: '매출액')에는 fuzzy 임계값(0.88)을 못 넘겨 완전 실패
(account_code='unknown...')로 이어졌다. DB 전수 스캔(`mapper.map(raw_label)`
실제 호출 경로 기준, combine.py 와 동일하게 raw 라벨을 그대로 넘김 — 미리
`normalize_account_name()`을 호출해 넘기면 `map()` 내부가 또 정규화해 이중적용
착시가 생기므로 주의): 이 결합표기 패턴 라벨 3,537종/10,226행(197개사) 중
**1,943종/5,229행(178개사)**이 old-fail→new-pass 로 회복됨(자본금·매출액·
유형자산·매입채무 등 핵심 계정 포함). 상세 = `docs/PARSING_RULES.md` R64.

수정: 숫자 목록 구분자 문자셋에 '와'/'과'/'및'을 추가(`[\\d,\\s와과및]`). 잔존
실패는 무관 별개 원인(numbering 접두어 미제거 '1)'류, account_maps 커버리지 갭
'만기보유금융자산'류) — 이 트랙 범위 밖. 계층2 재추출 불요(account_mapper는
계층3 combine.py 에서만 쓰임), std_v3 재백필로 소급 반영 필요(별도 백필 작업,
미착수·승인대기).

실행: python fin2/tests/test_amount_normalizer_note_ref_conjunction_r64.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import AccountMapper  # noqa: E402
from parser.common.amount_normalizer import normalize_account_name  # noqa: E402


def test_conjunction_note_ref_stripped():
    """★핵심 회귀 — '(주석N과M)'/'(주석N와M)' 결합표기가 통짜로 벗겨진다(수정 전엔 잔류)."""
    cases = {
        "Ⅰ. 매출액(주석13과 14)": "매출액",
        "Ⅰ.자본금(주석1과15)": "자본금",
        "1.현금및현금등가물(주석2와3)": "현금및현금등가물",
        "(2) 재고자산(주석2와7)": "재고자산",
        "1.매입채무(주석2와18)": "매입채무",
        "3. 만기보유금융자산(주석5,7과29)": "만기보유금융자산",  # 콤마+한글 접속사 혼합
        "2. 상각후취득원가측정금융부채(주석7,12,14,27과30)": "상각후취득원가측정금융부채",
    }
    for raw, expected in cases.items():
        got = normalize_account_name(raw)
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


def test_comma_only_note_ref_still_works():
    """기존 콤마전용 결합표기('(주석5,6)' 등)는 종전대로 정상 동작(무손실 불변식)."""
    cases = {
        "Ⅰ. 매출액(주석13)": "매출액",
        "현금및현금성자산 (주5,6)": "현금및현금성자산",
        "이익잉여금(주석 9,37)": "이익잉여금",
    }
    for raw, expected in cases.items():
        got = normalize_account_name(raw)
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


def test_end_to_end_mapping_recovered():
    """실사례(KG스틸 revenue) 매핑이 unknown→정상 canonical 로 회복된다."""
    mapper = AccountMapper()
    norm = normalize_account_name("Ⅰ. 매출액(주석13과 14)")
    result = mapper.map(norm)
    assert result.account_code == "is.revenue", result
    assert result.confidence == 1.0, result
    assert result.stage == "exact", result


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
