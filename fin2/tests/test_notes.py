"""fin2/extract/notes.py 단위감지 강화(_unit_factor) 테스트."""
from __future__ import annotations

from fin2.extract.notes import _unit_factor


def _check(name, cond):
    print(f"  {'OK ' if cond else 'FAIL'} {name}")
    assert cond, name


def test_unit_factor():
    rev = 100_000_000_000  # 매출 1,000억

    # 1) 이미 현실 범위(da/rev=4%) → 보정 없음(1.0)
    _check("plausible→1.0", _unit_factor(4_000_000_000, rev) == 1.0)

    # 2) ×1000 작음(백만원을 천원으로 오인): da 가 4,000,000 → /rev=4e-5(0.004%) 비현실
    #    ×1000 하면 4e9/rev=4% → factor 1000 선택
    _check("too_small→x1000", _unit_factor(4_000_000, rev) == 1e3)

    # 3) ×1000 큼(천원을 백만원으로 오인): da 4e12 → /rev=40(4000%) 비현실,
    #    ÷1000 하면 4e9/rev=4% → factor 1e-3
    _check("too_big→/1000", _unit_factor(4_000_000_000_000, rev) == 1e-3)

    # 4) 어떤 배율로도 현실 범위 못 듦(예: 0) → None 은 아니고 1.0(da 0)
    _check("zero_da→1.0", _unit_factor(0, rev) == 1.0)

    # 5) 매출 앵커 없음 → 보정 안 함(1.0)
    _check("no_rev→1.0", _unit_factor(4_000_000, None) == 1.0)

    # 6) 극단값: 어떤 배율도 [3e-4,2.0] 밖 → None(버림)
    #    da=5e18, rev=1e11 → base=5e7; ×1e-6=50(>2), 더 줄일 배율 없음 → None
    _check("hopeless→None", _unit_factor(5 * 10**18, rev) is None)


if __name__ == "__main__":
    print("test_unit_factor")
    test_unit_factor()
    print("통과")
