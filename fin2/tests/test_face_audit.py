"""Gate B face_audit 단위 테스트 — 독립 숫자 파서 + 범위 게이팅 + 행 롤업.

실행: python -m fin2.tests.test_face_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.face_audit import (  # noqa: E402
    parse_displayed, FaceLine, audit_std_row, STATUS_PASS, STATUS_FAIL, STATUS_PENDING,
    RowAudit, gate_status_for_row, GATE_PASS, GATE_FAIL_A, GATE_FAIL_B, GATE_PENDING,
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
    db = {"total_assets": 900}  # 보고서 1000 (표시단위 1단위 초과 = 실오류)
    bs = [_bs_line("bs.total_assets", 1000)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_FAIL
    assert ra.fail_fields == ["total_assets"]


def test_display_unit_tolerance():
    # 천원(ade=-3) 1단위(1,000원) 이내 = 발행사 반올림 → PASS.
    ra = audit_std_row({"total_assets": 1_234_000}, basis="consolidated",
                       bs_face=[_bs_line("bs.total_assets", 1235, ade=-3)],
                       is_face=[], cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    # 2단위(2,000원) 차이 = 실오류 → FAIL.
    ra2 = audit_std_row({"total_assets": 1_233_000}, basis="consolidated",
                        bs_face=[_bs_line("bs.total_assets", 1235, ade=-3)],
                        is_face=[], cf_face=[], is_comparative=False)
    assert ra2.status == STATUS_FAIL


def test_net_income_matches_attribution_sum():
    # 본문 당기순이익 라인이 불일치(3개월만)해도 지배+비지배 귀속 합과 일치 → PASS.
    is_face = [_bs_line("is.net_income", -502_592_034),
               _bs_line("is.controlling_ni", -1_903_963_591),
               _bs_line("is.noncontrolling_ni", -3_177_661)]
    ra = audit_std_row({"net_income": -1_907_141_252}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.n_fail == 0, ra.fields


def test_comparative_row_unmatched_is_pending_not_fail():
    # 비교행 값이 보고서 face(전 컬럼)에 없으면 → PENDING(절대 fail 아님: fail=0 보존).
    db = {"total_assets": 777}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_assets", 1200)]
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=True)
    assert ra.status == STATUS_PENDING
    assert ra.n_fail == 0


def test_comparative_row_matched_is_pass():
    # 비교행 값이 보고서 전 컬럼(all_cols face) 중 하나와 일치하면 → PASS(검증, 커버리지 확장).
    db = {"total_assets": 1200}
    bs = [_bs_line("bs.total_assets", 1000), _bs_line("bs.total_assets", 1200)]  # 전기 컬럼 1200
    ra = audit_std_row(db, basis="consolidated", bs_face=bs, is_face=[], cf_face=[],
                       is_comparative=True)
    assert ra.status == STATUS_PASS, ra.fields
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


def test_sign_flip_is_pass():
    # std 는 비용을 양수화(매출원가 +), 보고서는 괄호 음수(-). 절대값 충실 → PASS.
    db = {"cogs": 27747335376}
    is_line = FaceLine(statement="IS", basis="separate", acode="매출원가", canonical="is.cogs",
                       label="매출원가", displayed_value=-27747335376, adecimal=0)
    ra = audit_std_row(db, basis="separate", bs_face=[], is_face=[is_line], cf_face=[],
                       is_comparative=False)
    assert ra.status == STATUS_PASS
    assert ra.n_fail == 0


def _ra(status, fail_fields=()):
    return RowAudit(status=status, n_pass=0, n_fail=len(fail_fields), n_pending=0,
                    fields=[], fail_fields=list(fail_fields))


def test_gate_pass_pending_passthrough():
    assert gate_status_for_row(_ra(STATUS_PASS), {}) == GATE_PASS
    assert gate_status_for_row(_ra(STATUS_PENDING), {}) == GATE_PENDING


def test_gate_track_a_fail_is_fail_a():
    # Track A 출처 실패 = 확정버그 → fail_a(차단)
    ra = _ra(STATUS_FAIL, ["total_assets"])
    assert gate_status_for_row(ra, {"total_assets": "A"}) == GATE_FAIL_A


def test_gate_track_b_fail_is_fail_b():
    # 전 실패필드가 Track B = 휴리스틱 → fail_b(REVIEW, 메인뷰 노출)
    ra = _ra(STATUS_FAIL, ["cash"])
    assert gate_status_for_row(ra, {"cash": "B"}) == GATE_FAIL_B


def test_gate_mixed_fail_blocks_on_any_track_a():
    ra = _ra(STATUS_FAIL, ["cash", "total_assets"])
    assert gate_status_for_row(ra, {"cash": "B", "total_assets": "A"}) == GATE_FAIL_A


def test_gate_unknown_track_is_conservative_fail_a():
    # track 미상(None/누락)은 보수적으로 차단(fail_a)
    ra = _ra(STATUS_FAIL, ["revenue"])
    assert gate_status_for_row(ra, {"revenue": None}) == GATE_FAIL_A
    assert gate_status_for_row(ra, {}) == GATE_FAIL_A


def test_revenue_derived_verified_by_cogs_plus_gross_profit():
    # 매출액 단일 라인 부재 + std 가 cogs+gross_profit 로 파생 → 항등식 합 일치 시 PASS.
    is_face = [_bs_line("is.cogs", 800), _bs_line("is.gross_profit", 200)]
    ra = audit_std_row({"revenue": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    # 괄호 음수 cogs(=양수화 안 된 face)도 abs 로 일치.
    is_face2 = [_bs_line("is.cogs", -800), _bs_line("is.gross_profit", 200)]
    ra2 = audit_std_row({"revenue": 1000}, basis="consolidated",
                        bs_face=[], is_face=is_face2, cf_face=[], is_comparative=False)
    assert ra2.status == STATUS_PASS, ra2.fields


def test_net_income_label_unmatched_falls_back_to_attribution():
    # IS face 에 총 당기순이익 라인 부재(LABEL_UNMATCHED 상황)여도 지배+비지배 귀속 합과
    # 일치하면 PASS(보고서에 값 실재 검증). fail 아님·pending 아님.
    is_face = [_bs_line("is.controlling_ni", 900), _bs_line("is.noncontrolling_ni", 100)]
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=is_face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields
    assert ra.n_fail == 0


def test_net_income_label_unmatched_falls_back_to_cf_line():
    # IS face 에 net_income 라인 부재여도 CF 간접법 시작 '당기순이익'(cf.net_income_cf)과
    # 일치하면 PASS(동일 file 의 CF face 가 병합돼 있는 경우).
    face = [_bs_line("cf.net_income_cf", 1000)]
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PASS, ra.fields


def test_net_income_label_unmatched_no_alt_stays_pending_not_fail():
    # 보조 라인도 불일치면 LABEL_UNMATCHED(pending) 유지 — 절대 fail 아님(fail=0 보존).
    face = [_bs_line("is.controlling_ni", 900), _bs_line("is.noncontrolling_ni", 50)]  # 합 950≠1000
    ra = audit_std_row({"net_income": 1000}, basis="consolidated",
                       bs_face=[], is_face=face, cf_face=[], is_comparative=False)
    assert ra.status == STATUS_PENDING
    assert ra.n_fail == 0


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
