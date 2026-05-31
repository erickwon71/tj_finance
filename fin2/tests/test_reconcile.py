"""
reconcile.select_source 단위 테스트 (순수 함수, DB 비의존).

over-supersede 핵심 시나리오를 고정:
  - 부분 기재정정(라인 적음)은 완전한 원본을 이기지 못한다(리메드 2023 패턴).
  - anchor 보유가 완전성보다 우선(깨진 부분본이 라인만 많을 때 방어).
  - 완전성/anchor 동급이면 최신 filed_at(정정 우선).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.reconcile import select_source, _statement_of  # noqa: E402

_BS_ANCHOR = "bs.total_assets"
_IS_ANCHOR = "is.revenue"


def test_partial_amendment_loses_to_complete_original():
    # 리메드 2023 IS 패턴: 원본 25라인(anchor) vs 정정 12라인(anchor지만 깨짐)
    original = ("20240320001869", {f"is.x{i}" for i in range(24)} | {_IS_ANCHOR}, date(2024, 3, 20))
    partial = ("20240516001212", {f"is.y{i}" for i in range(11)} | {_IS_ANCHOR}, date(2024, 5, 16))
    best_rcept, _, _ = select_source([original, partial], _IS_ANCHOR)
    assert best_rcept == "20240320001869", "완전한 원본이 선택돼야 함(over-supersede 방지)"


def test_anchor_beats_more_lines_without_anchor():
    # anchor 없는 라인 부자 vs anchor 있는 소수 라인 → anchor 우선
    no_anchor = ("R1", {f"bs.x{i}" for i in range(50)}, date(2024, 1, 1))
    with_anchor = ("R2", {_BS_ANCHOR, "bs.cash"}, date(2024, 1, 1))
    best_rcept, _, _ = select_source([no_anchor, with_anchor], _BS_ANCHOR)
    assert best_rcept == "R2"


def test_tiebreak_latest_filed_wins():
    # 완전성·anchor 동급이면 최신 filed_at(정정 우선)
    older = ("R_OLD", {_BS_ANCHOR, "bs.cash", "bs.inventory"}, date(2024, 3, 1))
    newer = ("R_NEW", {_BS_ANCHOR, "bs.cash", "bs.inventory"}, date(2024, 5, 1))
    best_rcept, _, _ = select_source([older, newer], _BS_ANCHOR)
    assert best_rcept == "R_NEW"


def test_single_candidate():
    only = ("R1", {_BS_ANCHOR, "bs.cash"}, date(2024, 1, 1))
    best_rcept, _, _ = select_source([only], _BS_ANCHOR)
    assert best_rcept == "R1"


def test_statement_of_prefix():
    assert _statement_of("bs.total_assets") == "BS"
    assert _statement_of("is.revenue") == "IS"
    assert _statement_of("cf.operating") == "CF"
    assert _statement_of("note.depreciation") is None


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
