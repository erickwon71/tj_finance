"""Gate B face_audit 단위 테스트 — 독립 숫자 파서 + 범위 게이팅 + 행 롤업.

실행: python -m fin2.tests.test_face_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.face_audit import (  # noqa: E402
    parse_displayed, FaceLine, audit_std_row, STATUS_PASS, STATUS_FAIL, STATUS_PENDING,
)


def test_parse_displayed_basic():
    assert parse_displayed("1,234,567") == 1234567
    assert parse_displayed("(1,234)") == -1234        # 괄호 음수
    assert parse_displayed("△500") == -500            # 삼각형 음수
    assert parse_displayed("-12") == -12
    assert parse_displayed("0") == 0
    assert parse_displayed("") is None
    assert parse_displayed("   ") is None
    assert parse_displayed("N/A") is None
    assert parse_displayed("1,234.6") == 1235          # 소수 반올림


def _bs_line(canon, won, basis="consolidated", ade=0):
    # adecimal=0 이면 amount_won == displayed
    return FaceLine(statement="BS", basis=basis, acode="x", canonical=canon,
                    label="x", displayed_value=won, adecimal=ade)


def test_row_pass_when_all_inscope_match():
    db = {"total_assets": 1000, "total_liabilities": 600, "total_equity": 400}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_liabilities", 600),
          _bs_line("bs.total_equity", 400)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.n_fail == 0 and ra.n_pending == 0


def test_row_fail_on_value_diff():
    db = {"total_assets": 999}  # 보고서는 1000
    bs = [_bs_line("bs.total_assets", 1000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL
    assert ra.fail_fields == ["total_assets"]


def test_comparative_row_is_pending_not_fail():
    db = {"total_assets": 999}
    bs = [_bs_line("bs.total_assets", 1000)]  # col0 는 다른 연도지만 비교행이라 감사 보류
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=True)
    assert ra.status == STATUS_PENDING
    assert ra.n_fail == 0


def test_track_b_source_is_pending():
    db = {"total_assets": 1000}
    ra = audit_std_row(db, basis="consolidated", bs_face=[], is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PENDING  # face 비어있음 = Track B/미수록


def test_unit_scaled_match():
    # 천원 단위 표시(adecimal=-3): displayed 1234 → amount_won 1,234,000
    line = _bs_line("bs.total_assets", 1234, ade=-3)
    assert line.amount_won == 1234000
    db = {"total_assets": 1234000}
    ra = audit_std_row(db, basis="consolidated", bs_face=[line], is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS


def test_pending_blocks_pass():
    # 하나는 통과, 하나는 Track B(pending) → 행은 100% 인증 불가 → pending
    db = {"total_assets": 1000, "cfo": 500}
    bs = [_bs_line("bs.total_assets", 1000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)  # cf_face 비어있음 → cfo pending
    assert ra.status == STATUS_PENDING
    assert ra.n_pass == 1 and ra.n_pending == 1


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
