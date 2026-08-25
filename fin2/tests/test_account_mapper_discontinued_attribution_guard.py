"""
account_mapper 지배/비지배 귀속 중단·계속영업 성분 가드 회귀 테스트 (DB 비의존).

배경(2026-08-23, 케이엔더블유 00606664): '지배주주지분순이익(중단)'처럼 귀속(지배/
비지배) 라벨에 '중단'(중단영업/중단사업) 한정어가 붙으면 그건 계속+중단 합산
헤드라인 총계가 아니라 중단영업 성분만의 부분값이다. '순이익' 키워드가 있어 bare
지배지분 가드는 통과시키고, 퍼지가 헤드라인 alias와 근접하다고 보고 controlling_ni/
noncontrolling_ni 로 오매핑한다 — account_mapper.py 에 가드 신설로 차단(무매핑,
raw 보존).

후속(2026-08-25, DRB동일 00118266 — R43 254개사 Gate B 재감사 중 pass→fail_b 부수
발견): 위 가드는 '중단' 한정어만 검사해 **대칭 케이스인 '계속영업'을 놓쳤다** —
'지배기업의 소유주에 귀속될 계속영업당기순이익'(부분값, 18,327,708,908)이 헤드라인
합산(계속+중단, 29,912,789,124) 대신 controlling_ni 로 채택됐다. '계속영업' 성분도
'중단영업' 성분과 대칭적으로 부분값이므로 동일하게 차단하도록 가드를 확장했다.

근거: 메모리
`gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`
(부수발견 항목) · `docs/PARSING_RULES.md` R43 인접 부록C.

실행: python fin2/tests/test_account_mapper_discontinued_attribution_guard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_discontinued_component_still_blocked():
    # 기존(2026-08-23) '중단' 케이스 회귀 방지.
    m = get_mapper()
    for lbl in ("지배주주지분순이익(중단)", "지배기업소유주지분순이익(중단영업)",
                "비지배지분순이익(중단사업)"):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_continuing_component_now_blocked():
    # 신규(2026-08-25, DRB동일): '계속영업' 대칭 케이스.
    m = get_mapper()
    for lbl in (
        "지배기업의소유주에귀속될계속영업당기순이익",
        "지배주주지분순이익(계속영업)",
        "비지배지분순이익(계속영업)",
    ):
        r = m.map(lbl, fs_section="is")
        assert r.account_code.startswith("unknown."), f"{lbl} -> {r.account_code}"


def test_real_ni_attribution_labels_unaffected():
    # 과차단 방지: 계속/중단 한정어 없는 진짜 헤드라인 귀속 라벨은 여전히 매핑돼야 한다.
    m = get_mapper()
    r_c = m.map("지배기업소유주지분당기순이익", fs_section="is")
    assert r_c.account_code == "is.controlling_ni", r_c.account_code
    r_n = m.map("비지배지분당기순이익", fs_section="is")
    assert r_n.account_code == "is.noncontrolling_ni", r_n.account_code


def test_headline_continuing_operations_income_unaffected():
    # 과차단 방지: 귀속(지배/비지배) 없는 헤드라인 '계속영업이익' 자체는 기존
    # 영업이익 가드(is.operating_income 오매핑 차단)의 영역 — 이 가드와 무관해야
    # 하며 여전히 unknown(raw 보존)이어야 한다(정책 변화 없음, R21 회귀 확인).
    m = get_mapper()
    r = m.map("계속영업이익(손실)", fs_section="is")
    assert r.account_code.startswith("unknown."), r.account_code


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
