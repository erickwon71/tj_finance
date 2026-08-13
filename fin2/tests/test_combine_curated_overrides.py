"""curated override(2026-08-13) 회귀 테스트 (순수, DB 비의존).

docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md.

_resolve()의 stage-rank 숏컷이 총계/부모 라벨보다 구성요소/자식 라벨을 먼저 confirm해
버리는 취약점(버그#3/R15와 같은 계열)에 대해, revenue는 _REVENUE_TOTAL_OVERRIDE_CORPS,
trade_payables는 _TRADE_PAYABLES_PARENT_OVERRIDE_CORPS에 등재된 회사만 총계/부모를
선택하도록 좁힌 curated override를 검증한다. 등재되지 않은 회사(대조군)는 기존 동작
(자식/좁은 값 선택)이 그대로 유지돼야 한다 — 이게 이 설계의 핵심 제약(§2의 실측 결과,
일반화하면 각각 38:1·368:1로 회귀).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve  # noqa: E402


def _row(value, stage, label_raw, section_path="", node_role=None, table_seq=0):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "node_role": node_role,
            "table_seq": table_seq}


# --- revenue: is.revenue grand-total override -------------------------------------

def test_revenue_override_corp_picks_grand_total():
    # 한국전자홀딩스(00159254) 형태 재현: 자식 라벨('수수료수익')이 exact, 부모/총계
    # 라벨('영업수익')이 normalized — override 없으면 stage-rank 숏컷이 자식을 즉시 confirm.
    cands = {
        "is.revenue": [
            _row(4_637_783_457, "normalized", "I. 영업수익"),
            _row(1_614_747_527, "exact", "수수료수익"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00159254")
    assert confirmed["is.revenue"] == 4_637_783_457
    assert "is.revenue" not in conflicts


def test_revenue_non_override_corp_keeps_child_selection():
    # 대조군: SBI인베스트먼트(00156910) 형태 — 같은 구조(총계 vs 구성요소)지만 등재
    # 안 된 회사는 기존 동작(자식/exact 우선) 그대로 유지돼야 한다(§2-1 실측: 총계
    # 우선을 일반화하면 이런 회사가 303건 회귀).
    cands = {
        "is.revenue": [
            _row(4_637_783_457, "normalized", "I. 영업수익"),
            _row(1_614_747_527, "exact", "수수료수익"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00156910")
    assert confirmed["is.revenue"] == 1_614_747_527


def test_revenue_override_corp_no_grand_total_candidate_falls_through():
    # 등재 회사라도 이번 기간에 총계 라벨 자체가 없으면(개별 필터링 결과 grand가 빈
    # 리스트) 원래 rows 그대로 두고 정상 stage-rank 경로로 진행돼야 한다 — MISSING을
    # 새로 만들면 안 된다.
    cands = {
        "is.revenue": [
            _row(1_614_747_527, "exact", "수수료수익"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00159254")
    assert confirmed["is.revenue"] == 1_614_747_527


# --- trade_payables: bs.trade_payables parent(P) override --------------------------

def test_trade_payables_override_corp_picks_parent():
    # 현대공업(00164502) 등 5개사 형태 재현: 자식('단기매입채무')이 exact, 부모
    # ('매입채무 및 기타유동채무', node_role='P')가 normalized.
    cands = {
        "bs.trade_payables": [
            _row(5_000_000_000, "normalized", "매입채무 및 기타유동채무",
                 "부채>유동부채", node_role="P"),
            _row(3_200_000_000, "exact", "단기매입채무",
                 "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00164502")
    assert confirmed["bs.trade_payables"] == 5_000_000_000
    assert "bs.trade_payables" not in conflicts


def test_trade_payables_non_override_corp_keeps_narrow_child_selection():
    # 대조군: 등재 안 된 회사는 기존 동작(_NARROW_PREFER, 좁은/자식 값) 그대로 —
    # §2-2 실측: 부모 우선을 일반화하면 11,761건 회귀, 대다수 회사는 자식이 정답.
    cands = {
        "bs.trade_payables": [
            _row(5_000_000_000, "normalized", "매입채무 및 기타유동채무",
                 "부채>유동부채", node_role="P"),
            _row(3_200_000_000, "exact", "단기매입채무",
                 "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00999999")
    assert confirmed["bs.trade_payables"] == 3_200_000_000


def test_trade_payables_override_corp_no_parent_candidate_falls_through():
    # 등재 회사라도 이번 기간에 P 후보 자체가 없으면 원래 rows 그대로 진행.
    cands = {
        "bs.trade_payables": [
            _row(3_200_000_000, "exact", "단기매입채무", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00164502")
    assert confirmed["bs.trade_payables"] == 3_200_000_000


def test_no_corp_arg_defaults_to_no_override():
    # corp 인자 없이 호출(기존 호출부/스크립트 하위호환)하면 어떤 override도 안 걸린다.
    cands = {
        "is.revenue": [
            _row(4_637_783_457, "normalized", "I. 영업수익"),
            _row(1_614_747_527, "exact", "수수료수익"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["is.revenue"] == 1_614_747_527
