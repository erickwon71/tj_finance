"""
reconcile.select_source 단위 테스트 (순수 함수, DB 비의존).

후보 튜플 = (rcept, lines:set, filed_at, is_amendment).
우선순위(사전식): anchor 보유 > 기재정정(is_amendment) > 완전성(라인수) > filed_at 최신 > rcept.

고정 시나리오:
  - 부분 첨부정정(is_amendment=False, 라인 적음)은 완전한 원본을 못 이긴다(리메드 2023 over-supersede 방지).
  - 기재정정(is_amendment=True)은 완전성이 낮아도 원본을 대체한다(jiitech ×1000: 버그 원본이
    천원 오검출로 라인 수가 부풀려져도 올바른 기재정정본이 이김).
  - anchor 보유가 완전성보다 우선.
  - anchor·정정·완전성 동급이면 최신 filed_at.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.reconcile import select_source, _statement_of  # noqa: E402

_BS_ANCHOR = "bs.total_assets"
_IS_ANCHOR = "is.revenue"


def _cand(rcept, n_lines, filed_at, *, anchor=_IS_ANCHOR, prefix="is.x", is_amend=False):
    lines = {f"{prefix}{i}" for i in range(n_lines)} | {anchor}
    return (rcept, lines, filed_at, is_amend)


def test_partial_attachment_amendment_loses_to_complete_original():
    # 리메드 2023 IS: 원본(첨부정정 아님, 24라인) vs 첨부정정(is_amendment=False, 11라인, 깨짐).
    # 둘 다 is_amendment=False → 완전성으로 결정 → 원본 유지(over-supersede 방지).
    original = _cand("20240320001869", 24, date(2024, 3, 20), is_amend=False)
    attach = _cand("20240516001212", 11, date(2024, 5, 16), prefix="is.y", is_amend=False)
    best = select_source([original, attach], _IS_ANCHOR)
    assert best[0] == "20240320001869", "완전한 원본이 선택돼야 함(over-supersede 방지)"


def test_content_amendment_beats_buggy_original_even_with_fewer_lines():
    # jiitech 2022 IS: 버그 원본(is_amendment=False, 24라인 — 천원 오검출로 부풀려짐) vs
    # 기재정정본(is_amendment=True, 14라인, 올바른 단위). 기재정정이 이겨야 함.
    buggy_original = _cand("20230323001579", 24, date(2023, 3, 23), is_amend=False)
    content_fix = _cand("20230324001306", 14, date(2023, 3, 27), prefix="is.y", is_amend=True)
    best = select_source([buggy_original, content_fix], _IS_ANCHOR)
    assert best[0] == "20230324001306", "기재정정본이 원본을 대체해야 함"


def test_anchor_beats_more_lines_without_anchor():
    # anchor 없는 라인 부자 vs anchor 있는 소수 라인 → anchor 우선
    no_anchor = ("R1", {f"bs.x{i}" for i in range(50)}, date(2024, 1, 1), False)
    with_anchor = ("R2", {_BS_ANCHOR, "bs.cash"}, date(2024, 1, 1), False)
    best = select_source([no_anchor, with_anchor], _BS_ANCHOR)
    assert best[0] == "R2"


def test_content_amendment_does_not_beat_nonanchor():
    # 기재정정이라도 anchor 없으면 anchor 보유 원본을 못 이김(anchor 가 최상위).
    amend_no_anchor = ("R_AMEND", {f"bs.x{i}" for i in range(40)}, date(2024, 5, 1), True)
    orig_anchor = ("R_ORIG", {_BS_ANCHOR, "bs.cash"}, date(2024, 1, 1), False)
    best = select_source([amend_no_anchor, orig_anchor], _BS_ANCHOR)
    assert best[0] == "R_ORIG"


def test_tiebreak_latest_filed_wins():
    # anchor·정정·완전성 동급이면 최신 filed_at
    older = ("R_OLD", {_BS_ANCHOR, "bs.cash", "bs.inventory"}, date(2024, 3, 1), False)
    newer = ("R_NEW", {_BS_ANCHOR, "bs.cash", "bs.inventory"}, date(2024, 5, 1), False)
    best = select_source([older, newer], _BS_ANCHOR)
    assert best[0] == "R_NEW"


def test_single_candidate():
    only = ("R1", {_BS_ANCHOR, "bs.cash"}, date(2024, 1, 1), False)
    best = select_source([only], _BS_ANCHOR)
    assert best[0] == "R1"


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
