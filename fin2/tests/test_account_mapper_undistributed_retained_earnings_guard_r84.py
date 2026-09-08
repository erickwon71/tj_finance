"""
account_mapper "미처분이익잉여금" 가드 회귀 테스트 (DB 비의존). R84.

배경(항목2(나) 트랙, HS애드 00140168 등 — docs/plans/section_def_fallback_wrong_
sibling_unit_design_2026-09-06.md "2026-09-08 재개" 절): "미처분이익잉여금"은
2026-07-18(D4 2R)에 account_maps/bs_accounts.py 의 exact alias 목록에서 의도적으로
제거됐다 — 총계('이익잉여금')의 sub-line(총 = 미처분 + 적립금 등)이라 총계 자리에
오면 과소·값충돌이기 때문이다. 그런데 Stage 3 fuzzy 의 "포함관계"(containment)
매칭이 alias '이익잉여금'이 '미처분이익잉여금'의 부분문자열이라는 이유만으로 그대로
되살려 bs.retained_earnings 에 오매핑했다 — '미처분연결이익잉여금'·'미처분전이익
잉여금'·'당기말/분기말/반기말미처분이익잉여금' 등 접두/접미 변형까지 전부 같은
경로로 새어나왔다. 같은 필링에 진짜 총계 라인이 있으면 conflict 로 안전하게
보류되지만, 없으면(흔함 — 인터림 BS 가 적립금 세부내역 없이 미처분 잔액만 보여주는
서식) 유일한 후보로 그대로 확정됐다.

DB 전수 스캔(2026-09-08)으로 실측 확정: 이익잉여금 계열 라벨이 있는 274,659개
(corp,rcept,basis) 조합 중 1,073건(247개사)이 "미처분만 있고 총계 라인이 없는"
위험군이었고, 그중 656행이 이미 라이브 std_financials_v3.retained_earnings 에
이 오염값 그대로 저장돼 있었다(00152437 표본 자체 시계열로 실제 오염 확인).

수정: parser/common/account_mapper.py::map() 에 Stage 3 진입 전 가드 추가 —
정규화된 라벨에 "미처분"과 ("이익잉여금" 또는 "결손금")이 함께 있으면(bs/미지정
섹션 한정) 무매핑(unknown)으로 차단. 결측이 오염보다 낫다는 원칙 재적용.

실행: python fin2/tests/test_account_mapper_undistributed_retained_earnings_guard_r84.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper  # noqa: E402


def test_bare_undistributed_retained_earnings_blocked():
    m = get_mapper()
    r = m.map("미처분이익잉여금", fs_section="bs")
    assert r.account_code == "unknown.미처분이익잉여금", r.account_code


def test_consolidated_undistributed_retained_earnings_blocked():
    # HS애드(00140168) 2008H1 실측 라벨.
    m = get_mapper()
    r = m.map("3.미처분연결이익잉여금", fs_section="bs")
    assert r.account_code.startswith("unknown."), r.account_code


def test_prefixed_variant_blocked():
    # 00102353(2007Q1/H1) 실측 라벨.
    m = get_mapper()
    r = m.map("미처분전이익잉여금", fs_section="bs")
    assert r.account_code.startswith("unknown."), r.account_code


def test_period_qualified_variants_blocked():
    # 00102432(2003~2004) 실측 라벨 변형들.
    m = get_mapper()
    for label in ("6.당기말미처분이익잉여금", "6.분기말미처분이익잉여금", "6.반기말미처분이익잉여금"):
        r = m.map(label, fs_section="bs")
        assert r.account_code.startswith("unknown."), (label, r.account_code)


def test_undistributed_with_deficit_parenthetical_blocked():
    # 00152437 등 다수 실측 라벨("미처분이익잉여금(미처리결손금)").
    m = get_mapper()
    r = m.map("미처분이익잉여금(미처리결손금)", fs_section="bs")
    assert r.account_code.startswith("unknown."), r.account_code


def test_bare_retained_earnings_total_still_maps_correctly():
    # 진짜 총계 라인(가드 대상 아님)은 그대로 정확히 매핑돼야 한다.
    m = get_mapper()
    r = m.map("이익잉여금", fs_section="bs")
    assert r.account_code == "bs.retained_earnings", r.account_code
    assert r.stage == "exact", r.stage


def test_retained_earnings_with_deficit_parenthetical_still_maps_correctly():
    m = get_mapper()
    r = m.map("이익잉여금(결손금)", fs_section="bs")
    assert r.account_code == "bs.retained_earnings", r.account_code


def test_bare_deficit_alone_still_maps_correctly():
    # "미처분"이 없는 "결손금" 단독은 가드 대상이 아니다(음수 총계 표현, exact alias).
    m = get_mapper()
    r = m.map("결손금", fs_section="bs")
    assert r.account_code == "bs.retained_earnings", r.account_code


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
