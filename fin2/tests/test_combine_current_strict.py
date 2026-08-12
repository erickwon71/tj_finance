"""_CURRENT_STRICT(bs.trade_payables 등) stage-rank 숏컷 우회 버그 회귀 테스트 (순수, DB 비의존).

docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md ③ / docs/plans/
gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md 버그 #3.

_resolve()가 유동/비유동 후보가 섞인 _CURRENT_STRICT canonical(bs.trade_payables 등)에
대해 stage-rank 숏컷으로 비유동 후보를 그대로 확정해버리지 않고, 반드시 비유동 후보를
먼저 걸러낸 뒤 진행하는지 검증한다 — 재현 케이스: 경남제약(00307028) 2024FY, 노루페인트
계열 등 21개사 52건 near-zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve, _is_noncurrent  # noqa: E402


def _row(value, stage, label_raw, section_path):
    """Minimal candidate row shape (subset of _map_rows() output actually read by
    _resolve())."""
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "table_seq": 0}


def test_noncurrent_label_no_longer_outranks_current_via_stage_shortcut():
    # 경남제약(00307028) 2024FY separate 실측 재현: 비유동 라인의 라벨 텍스트 자체엔
    # '비유동'/'장기' 표기가 전혀 없다(section_path로만 구분됨) — '매입채무및기타채무'가
    # exact alias(account_maps/bs_accounts.py)라 'exact' 단계를 얻는 반면, 정상적인
    # 유동부채 라인('매입채무 및 기타유동채무', 공백 포함 변형)은 whitespace 정규화를
    # 거쳐 'normalized' 단계에 그친다. 수정 전에는 top_vals가 exact 단일값(6,000,000)
    # 으로 즉시 collapse되어 _reduce_conflict()의 current-strict 필터가 아예 호출되지
    # 않았다.
    cands = {
        "bs.trade_payables": [
            _row(8_206_288_902, "normalized", "매입채무 및 기타유동채무", "부채>유동부채"),
            _row(6_000_000, "exact", "매입채무및기타채무", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.trade_payables"] == 8_206_288_902
    assert "bs.trade_payables" not in conflicts


def test_noncurrent_label_text_alone_still_caught():
    # 00113997/00670340류: 비유동 라인 라벨 자체에 '장기'가 있는 케이스(원래도
    # _NONCURRENT_RE가 잡아야 했으나, stage-rank 숏컷이 먼저 confirm해버려 우회당했다).
    cands = {
        "bs.trade_payables": [
            _row(47_463_701_747, "exact", "매입채무및기타채무 (주5,6,11,16,35,39)", "부채>유동부채"),
            _row(0, "exact", "장기매입채무및기타채무", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.trade_payables"] == 47_463_701_747


def test_only_noncurrent_candidates_present_left_untouched():
    # 유동 후보가 아예 없으면(비정상 케이스) 필터가 전부 걸러내 빈 리스트가 되지 않도록
    # 원래 rows를 그대로 둔다 — MISSING을 새로 만들지 않는다.
    cands = {"bs.trade_payables": [_row(123, "exact", "장기매입채무", "부채>비유동부채")]}
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.trade_payables"] == 123


def test_two_current_candidates_still_go_through_normal_conflict_path():
    # 유동 후보끼리 진짜로 갈리면(둘 다 통과) 기존 충돌처리(HOLD)가 정상 동작해야 한다 —
    # 이 필터가 유동 후보끼리의 판단까지 대신 내리지 않는다.
    cands = {
        "bs.trade_payables": [
            _row(100, "exact", "매입채무", "부채>유동부채"),
            _row(200, "exact", "매입채무", "부채>유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert "bs.trade_payables" not in confirmed
    assert "bs.trade_payables" in conflicts


def test_is_noncurrent_checks_section_path_not_just_label():
    row_label_only = {"label_raw": "장기매입채무", "section_path": "부채>유동부채"}
    row_section_only = {"label_raw": "매입채무및기타채무", "section_path": "부채>비유동부채"}
    row_neither = {"label_raw": "매입채무", "section_path": "부채>유동부채"}
    assert _is_noncurrent(row_label_only) is True
    assert _is_noncurrent(row_section_only) is True
    assert _is_noncurrent(row_neither) is False
