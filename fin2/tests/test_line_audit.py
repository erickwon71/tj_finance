"""Gate B Phase B line_audit 단위 테스트 — won_match 허용오차 + 라인 reconcile 분류.

실행: python -m fin2.tests.test_line_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.face_audit import FaceLine  # noqa: E402
from fin2.audit.line_audit import (  # noqa: E402
    won_match, reconcile_report_lines, reconcile_report_lines_text,
    REASON_VALUE_DIFF, REASON_MISSING,
)


def _tface(canon, won, basis="consolidated", ade=0):
    """Track B(텍스트) face 라인 — acode=라벨(비XBRL), canonical 매핑됨."""
    return FaceLine(statement=None, basis=basis, acode=canon, canonical=canon,
                    label=canon, displayed_value=won, adecimal=ade, is_cumulative=True)


def _tfact(canon, won, basis="consolidated", ade=0):
    return {"canonical_account": canon, "basis": basis, "adecimal": ade, "amount_won": won}


def _face(acode, won, basis="consolidated", ade=0, cum=False):
    """Track A face 라인(acode 접두 ifrs/dart). adecimal<0 면 amount_won = won.
    여기선 amount_won 을 직접 통제하려 ade=0(=displayed) 사용."""
    return FaceLine(statement=None, basis=basis, acode=acode, canonical=None,
                    label=acode, displayed_value=won, adecimal=ade, is_cumulative=cum)


def _fact(acode, won, basis="consolidated", ade=0, cum=False):
    return {"acode": acode, "basis": basis, "is_cumulative": cum,
            "adecimal": ade, "amount_won": won}


def test_won_match_tolerance():
    # adecimal=0 → tol=1: ±1 허용
    assert won_match(1000, 1000, 0)
    assert won_match(1000, 1001, 0)
    assert not won_match(1000, 1002, 0)
    # adecimal=-3(천원 표시) → tol=1000
    assert won_match(1_000_000, 1_000_500, -3)
    assert not won_match(1_000_000, 1_002_000, -3)
    # 부호반대는 기본 불일치(라인감사는 리터럴 셀↔추출값)
    assert not won_match(1000, -1000, 0)
    assert won_match(1000, -1000, 0, allow_sign=True)


def test_reconcile_all_match():
    face = [_face("ifrs-full_Assets", 1000), _face("dart_Revenue", 500, cum=True)]
    facts = [_fact("ifrs-full_Assets", 1000), _fact("dart_Revenue", 500, cum=True)]
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_lines == 2 and r.n_match == 2
    assert r.n_value_diff == 0 and r.n_missing == 0 and r.n_extra == 0
    assert r.line_gate_status == "pass"


def test_reconcile_value_diff():
    face = [_face("ifrs-full_Assets", 1000)]
    facts = [_fact("ifrs-full_Assets", 1234)]   # >tol 차이
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_value_diff == 1 and r.n_match == 0
    assert r.value_diffs[0].reason == REASON_VALUE_DIFF
    assert r.value_diffs[0].report_won == 1000 and r.value_diffs[0].db_won == 1234
    assert r.line_gate_status == "fail_a"


def test_reconcile_missing_in_db():
    face = [_face("ifrs-full_Assets", 1000), _face("dart_Foo", 7)]
    facts = [_fact("ifrs-full_Assets", 1000)]    # dart_Foo 가 DB 에 없음
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_missing == 1 and r.n_match == 1
    assert r.missing[0].reason == REASON_MISSING and r.missing[0].acode == "dart_Foo"
    assert r.line_gate_status == "pass"          # missing 은 차단 아님(측정 우선)


def test_reconcile_extra_in_db():
    face = [_face("ifrs-full_Assets", 1000)]
    facts = [_fact("ifrs-full_Assets", 1000), _fact("dart_Bar", 9)]   # DB 잉여
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_extra == 1 and r.n_match == 1 and r.n_value_diff == 0


def test_basis_distinguished():
    # 같은 acode 라도 basis 다르면 별개 라인
    face = [_face("ifrs-full_Assets", 1000, basis="consolidated"),
            _face("ifrs-full_Assets", 800, basis="separate")]
    facts = [_fact("ifrs-full_Assets", 1000, basis="consolidated"),
             _fact("ifrs-full_Assets", 800, basis="separate")]
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_lines == 2 and r.n_match == 2 and r.n_value_diff == 0


def test_text_supplement_lines_ignored():
    # acode 가 XBRL 접두 아닌 라인(텍스트 보충)은 Track A 대조 대상 아님 → 미집계
    face = [_face("ifrs-full_Assets", 1000), FaceLine(
        statement="IS", basis="consolidated", acode="매출액", canonical="is.revenue",
        label="매출액", displayed_value=500, adecimal=0)]
    facts = [_fact("ifrs-full_Assets", 1000)]
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_lines == 1 and r.n_match == 1   # 텍스트 라인 제외
    assert r.n_missing == 0


def test_basis_none_notes_cells_excluded():
    # basis=None(주석 컨텍스트, 다중셀 동일태그) 라인은 본문 대조 대상 아님 → 미집계.
    # 같은 acode 가 face/fact 에서 서로 다른 셀을 가리켜도 false VALUE_DIFF 가 나면 안 됨.
    face = [_face("ifrs-full_Revenue", 892359, basis="consolidated"),
            _face("ifrs-full_Revenue", 227701, basis=None)]   # 주석 셀(다른 값)
    facts = [_fact("ifrs-full_Revenue", 892359, basis="consolidated"),
             _fact("ifrs-full_Revenue", 300000, basis=None)]   # 주석 셀(또 다른 값)
    r = reconcile_report_lines("R1", face, facts)
    assert r.n_lines == 1 and r.n_match == 1          # 본문(연결)만 대조
    assert r.n_value_diff == 0 and r.n_extra == 0     # 주석 셀 충돌 무시


def test_trackb_current_value_in_report_set():
    # 보고서는 당기+전기 컬럼(리터럴 다수), fact_v2 당기값이 그 집합에 있으면 match.
    face = [_tface("bs.total_assets", 1000), _tface("bs.total_assets", 800)]  # 당기/전기
    facts = [_tfact("bs.total_assets", 1000)]   # DB 당기값
    r = reconcile_report_lines_text("R1", face, facts)
    assert r.n_lines == 1 and r.n_match == 1 and r.n_value_diff == 0


def test_trackb_value_diff():
    # DB 당기값이 보고서 어느 컬럼에도 없음 → 손상 후보(차단).
    face = [_tface("is.revenue", 500), _tface("is.revenue", 400)]
    facts = [_tfact("is.revenue", 777)]
    r = reconcile_report_lines_text("R1", face, facts)
    assert r.n_value_diff == 1 and r.n_match == 0
    assert r.value_diffs[0].reason == REASON_VALUE_DIFF and r.value_diffs[0].db_won == 777


def test_trackb_missing_when_reader_absent():
    # fact_v2 에 있는 canonical 을 리더가 보고서에서 못 찾음 → MISSING(커버 갭, 비차단).
    face = [_tface("bs.total_assets", 1000)]
    facts = [_tfact("bs.total_assets", 1000), _tfact("cf.operating", 300)]
    r = reconcile_report_lines_text("R1", face, facts)
    assert r.n_match == 1 and r.n_missing == 1
    assert r.missing[0].reason == REASON_MISSING


def test_trackb_unmapped_fact_skipped():
    # canonical=None(미매핑) fact 는 대조 불가 → 집계 제외.
    face = [_tface("bs.total_assets", 1000)]
    facts = [_tfact("bs.total_assets", 1000), _tfact(None, 555)]
    r = reconcile_report_lines_text("R1", face, facts)
    assert r.n_lines == 1 and r.n_match == 1


def test_trackb_basis_distinguished():
    face = [_tface("bs.total_assets", 1000, basis="consolidated"),
            _tface("bs.total_assets", 800, basis="separate")]
    facts = [_tfact("bs.total_assets", 1000, basis="consolidated"),
             _tfact("bs.total_assets", 800, basis="separate")]
    r = reconcile_report_lines_text("R1", face, facts)
    assert r.n_lines == 2 and r.n_match == 2 and r.n_value_diff == 0


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
