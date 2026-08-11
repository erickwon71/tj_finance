"""BS 항등식(자산=부채+자본) 이상치 탐지 회귀 테스트 (합성 행, DB 비의존).

배경 — pre-2015 파일럿 백필 검증(2026-08-10) 중 발견: KG케미칼 등 일부 filer는 "부채총계"
당기(col0) 셀만 괄호로 감싸 표준 괄호=음수 관례로 읽으면 부채가 음수가 된다. 반면
"부채와자본총계"(결합행)는 매번 자산과 정확히 일치해 원문에 실제 문제가 있음을 시사한다.
R0 원칙(계층2 는 판단 없이 전사)상 값은 안 고치고, `detect_bs_identity_anomalies`가 여기서
**표시만** 한다(계층3 이 보정 여부 판단).

실행: python -m pytest fin2/tests/test_bs_identity_anomaly.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit.line_anomaly import detect_bs_identity_anomalies  # noqa: E402
from fin2.extract.report_lines import ReportLineRow  # noqa: E402


def _row(label_raw, value_won, *, col_index=0, basis="consolidated",
         table_seq=0, row_order=0) -> ReportLineRow:
    return ReportLineRow(
        corp_code="00101220", rcept_no="20030814000816",
        report_fiscal_year=2003, report_fiscal_period="H1",
        statement="BS", basis=basis, label_raw=label_raw, col_index=col_index,
        context_fiscal_year=2003, period_kind="instant", is_cumulative=False,
        value_won=value_won, adecimal=0, unit_source="declared", source_ref="x",
        context_raw="x", table_seq=table_seq, row_order=row_order,
    )


def test_identity_holds_no_anomaly():
    lines = [
        _row("자산총계", 100), _row("부채총계", 60), _row("자본총계", 40),
    ]
    assert detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c") == []


def test_kg_chemical_pattern_confirmed_by_combined_total():
    """실측 재현 — KG케미칼 20030814000816: 부채총계 부호가 뒤집혀 있고, 부채와자본총계
    (결합행)는 자산과 정확히 일치 → confidence=high, SIGN 으로 분류돼야 한다."""
    lines = [
        _row("자산총계", 118_690_610_298),
        _row("부채총계", -125_630_854_796),   # 원문 "(125,630,854,796)" 그대로 전사된 음수
        _row("자본총계", -6_940_244_498),
        _row("부채와자본총계", 118_690_610_298),  # 결합행은 정확 → 강한 근거
    ]
    out = detect_bs_identity_anomalies(lines, rcept_no="20030814000816", corp_code="00101220")
    assert len(out) == 1
    a = out[0]
    assert a.evidence == "bs_identity_confirmed"
    assert a.confidence == "high"
    assert a.label_raw == "부채총계"
    assert a.original_value == -125_630_854_796
    # 항등식이 함의하는 값 = 자산 - 자본 = 125,630,854,796(양수)
    assert a.suggested_value == 125_630_854_796
    assert a.anomaly_kind == "SIGN"          # reference == -observed


def test_mismatch_without_combined_total_is_low_confidence():
    """결합행이 없으면(또는 그것도 안 맞으면) '뭔가 안 맞는다'만 낮은 신뢰도로 표시하고
    suggested_value 는 추측하지 않는다(어느 쪽이 틀렸는지 확정 못 함)."""
    lines = [
        _row("자산총계", 100), _row("부채총계", 60), _row("자본총계", 30),  # 100 != 90
    ]
    out = detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c")
    assert len(out) == 1
    assert out[0].evidence == "bs_identity"
    assert out[0].confidence == "low"
    assert out[0].suggested_value is None


def test_combined_total_present_but_also_wrong_stays_low_confidence():
    lines = [
        _row("자산총계", 100), _row("부채총계", 60), _row("자본총계", 30),
        _row("부채와자본총계", 95),   # 결합행도 자산(100)과 안 맞음 → 확정 근거 아님
    ]
    out = detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c")
    assert len(out) == 1
    assert out[0].confidence == "low"


def test_ambiguous_duplicate_label_excluded_not_guessed():
    """같은 개념이 다른 값으로 중복되면(모호) 대조 자체를 하지 않는다(추측 금지, `_bs_concepts`
    와 동일 원칙)."""
    lines = [
        _row("자산총계", 100),
        _row("부채총계", 60, table_seq=0), _row("부채총계", 61, table_seq=1),  # 값이 다른 중복
        _row("자본총계", 40),
    ]
    assert detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c") == []


def test_within_tolerance_no_anomaly():
    """반올림급 오차(상대 0.1% 이내)는 이상치로 안 본다."""
    lines = [
        _row("자산총계", 1_000_000), _row("부채총계", 600_500), _row("자본총계", 399_600),
    ]  # diff = -100, 상대오차 0.01%
    assert detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c") == []


def test_separate_basis_checked_independently():
    lines = [
        _row("자산총계", 100, basis="separate"),
        _row("부채총계", 200, basis="separate"),   # 명백히 틀림 — separate 만 이상치
        _row("자본총계", 40, basis="separate"),
        _row("자산총계", 50, basis="consolidated"),
        _row("부채총계", 30, basis="consolidated"),
        _row("자본총계", 20, basis="consolidated"),
    ]
    out = detect_bs_identity_anomalies(lines, rcept_no="r", corp_code="c")
    assert len(out) == 1
    assert out[0].basis == "separate"
