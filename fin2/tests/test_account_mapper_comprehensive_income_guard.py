"""
account_mapper 포괄손익 귀속 가드 확장 회귀 테스트 (DB 비의존).

배경(NH투자증권 Gate B controlling_ni fail_b 근본원인 조사, 2026-08-25): 원래 가드
(account_mapper.py:191)는 '포괄손익'(붙임표기)만 검사했는데, 다수 필터社(증권사뿐
아니라 일반 상장사도 — 전수검사 254개사 실측)가 '포괄이익'/'포괄손실'로 **쪼개서**
표기한다('지배주주지분포괄이익'·'비지배지분포괄손실' 등). 이 변형은 원래 가드를
못 넘어 fuzzy 매칭으로 is.controlling_ni/is.noncontrolling_ni 에 오매핑됐다
(총포괄이익 귀속 값이 순이익 귀속 자리를 오염) — NH투자증권 FY2015 실측:
215,832백만(총포괄이익, 오답) vs 215,070백만(db_won 정답).

전수검사(283,030개 원문 XML): 오탐 3,273건(254개사/2,778 filing) 전부 순수 '포괄'
개념이었고, '순이익'/'당기순'이 같이 들어간 하이브리드 라벨은 0건 — 가드를 넓혀도
정답을 잘못 차단할 위험 없음을 확인 후 적용.

근거: 메모리
`gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`.

실행: python fin2/tests/test_account_mapper_comprehensive_income_guard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_split_form_comprehensive_income_blocked():
    # 신규: '포괄이익'/'포괄손실'(쪼개진 표기) — 원래 가드가 못 잡던 변형.
    m = get_mapper()
    for lbl in (
        "지배주주지분포괄이익",
        "비지배지분포괄손실",
        "지배기업지분포괄이익",
        "지배기업소유주지분총포괄이익",
        "비지배지분총포괄이익(손실)",
        "지배기업의소유주에게귀속되는총포괄이익(손실)",
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_joined_form_comprehensive_income_still_blocked():
    # 기존(붙임표기 '포괄손익') 가드 회귀 방지.
    m = get_mapper()
    for lbl in ("포괄손익, 지배기업소유주귀속지분", "총포괄손익,비지배지분"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_real_ni_attribution_labels_unaffected():
    # 과차단 방지: '순이익'/'당기순'이 실제로 들어간 진짜 NI 귀속 라벨은 여전히 매핑돼야 한다.
    m = get_mapper()
    r_c = m.map("지배기업소유주지분당기순이익", fs_section="is")
    assert r_c.account_code == "is.controlling_ni", r_c.account_code
    r_n = m.map("비지배지분당기순이익", fs_section="is")
    assert r_n.account_code == "is.noncontrolling_ni", r_n.account_code


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
