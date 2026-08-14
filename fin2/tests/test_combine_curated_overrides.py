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


def test_trade_payables_override_corp_picks_parent_2026_08_14_expansion():
    # 확장분(2026-08-14, docs/qa/gate_b_faila_residual_triage_2026-08-14.md §2)
    # KCC건설(00105466) 실제 원문 XBRL 값 재현(20250320001281.xml:7693-7716):
    # 부모 ACODE=ifrs-full_TradeAndOtherCurrentPayables, 자식
    # ACODE=ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers.
    cands = {
        "bs.trade_payables": [
            _row(232_367_566_122, "normalized", "매입채무 및 기타채무",
                 "부채>유동부채", node_role="P"),
            _row(182_916_925_475, "exact", "매입채무",
                 "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00105466")
    assert confirmed["bs.trade_payables"] == 232_367_566_122
    assert "bs.trade_payables" not in conflicts


def test_trade_payables_override_corp_no_parent_candidate_falls_through():
    # 등재 회사라도 이번 기간에 P 후보 자체가 없으면 원래 rows 그대로 진행.
    cands = {
        "bs.trade_payables": [
            _row(3_200_000_000, "exact", "단기매입채무", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00164502")
    assert confirmed["bs.trade_payables"] == 3_200_000_000


# --- trade_payables: bs.trade_payables additive override ---------------------------
#
# ★실측으로 확인된 함정 #1: 두 번째(형제) 라벨은 AccountMapper 별칭표를 거쳐 자기
# 고유의 canonical 로 매핑된다('기타지급채무' -> bs.other_current_payables 등,
# bs.trade_payables 가 아니다) — LG화학 실측 _map_label() 확인. 즉 두 라벨은
# cands 안에서 서로 다른 canonical 버킷에 들어간다. 첫 구현은 둘 다 같은
# canonical(bs.trade_payables) 의 rows 리스트 안에 있다고 잘못 가정한 목이라
# 실측 백필에서 발동하지 않는 회귀가 있었다(scoped Gate B recheck으로 발견) —
# 아래 목은 실제 구조(서로 다른 canonical)를 재현한다.
#
# ★실측으로 확인된 함정 #2: override 키는 corp 단독이 아니라 (corp, fy, period).
# corp 단독 키로 scoped 백필+Gate B recheck 했더니 같은 회사의 과거 모든 기간
# (2010~2024)이 새로 fail_b로 대규모 회귀했다 — "두 라인 합 = report_won"은 원문
# 재대조로 확인한 그 특정 필링에서만 성립한다. 그래서 _resolve() 는 fy/period 도
# 받아 (corp, fy, period) 3-튜플로 게이팅한다.

def test_trade_payables_additive_override_registered_period_sums_both_labels():
    # LG화학(00356361) FY2025 형태 재현(등재된 정확한 (corp,fy,period)): 매입채무
    # (bs.trade_payables)+기타지급채무(bs.other_current_payables) 둘 다 F 라인으로만
    # 존재하고 결합 총계(P) 라인 자체가 없음 — 두 값의 합이 report_won과 정확히
    # 일치(원문 XBRL 만기분석표 fact와 독립적으로 확인됨, §1).
    cands = {
        "bs.trade_payables": [
            _row(8_000_000_000, "exact", "매입채무", "부채>유동부채", node_role="F"),
        ],
        "bs.other_current_payables": [
            _row(2_518_983_000, "exact", "기타지급채무 (주3,5,30)",
                 "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00356361", 2025, "FY")
    assert confirmed["bs.trade_payables"] == 10_518_983_000
    assert "bs.trade_payables" not in conflicts


def test_trade_payables_additive_override_other_period_same_corp_unaffected():
    # ★회귀 재현 방지 테스트: corp가 등재돼 있어도 fy/period가 등재된 정확한
    # 튜플과 다르면(예: LG화학 FY2020) override가 발동하면 안 된다 — 이 세션에서
    # 실측으로 확인한 함정(corp 단독 키였을 때 과거 100건+ 회귀)의 재발 방지.
    cands = {
        "bs.trade_payables": [
            _row(8_000_000_000, "exact", "매입채무", "부채>유동부채", node_role="F"),
        ],
        "bs.other_current_payables": [
            _row(2_518_983_000, "exact", "기타지급채무", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00356361", 2020, "FY")
    assert confirmed["bs.trade_payables"] == 8_000_000_000


def test_trade_payables_additive_override_label_suffix_stripped():
    # 각주번호 접미사('(주4,5,19,36)' 등)가 붙어도 _norm_label 정규화 후
    # startswith 매칭으로 여전히 발동해야 한다(§3 근거).
    cands = {
        "bs.trade_payables": [
            _row(1_000, "exact", "유동매입채무(주1)", "부채>유동부채", node_role="F"),
        ],
        "bs.other_current_payables": [
            _row(2_000, "exact", "단기미지급금(주2,3)", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00109310", 2025, "FY")
    assert confirmed["bs.trade_payables"] == 3_000


def test_trade_payables_additive_override_noncurrent_excluded():
    # 비유동 변형('장기매입채무' 등)은 _is_noncurrent()로 배제 — R15와 동일 가드.
    cands = {
        "bs.trade_payables": [
            _row(8_000_000_000, "exact", "매입채무", "부채>유동부채", node_role="F"),
        ],
        "bs.other_current_payables": [
            _row(999_999_999, "exact", "기타지급채무", "부채>비유동부채",
                 node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00356361", 2025, "FY")
    # 두 번째 라벨('기타지급채무')이 비유동이라 매칭에서 배제되므로 두 라벨 모두
    # 못 채운다 — 원래 stage-rank 경로로 자연스럽게 폴백.
    assert confirmed["bs.trade_payables"] == 8_000_000_000


def test_trade_payables_additive_override_missing_one_label_falls_through():
    # 두 라벨 중 하나만 있으면(필링마다 라벨이 미세하게 바뀔 수 있음) 원래
    # stage-rank 경로로 자연스럽게 폴백 — 결측을 새로 만들지 않음.
    cands = {
        "bs.trade_payables": [
            _row(8_000_000_000, "exact", "매입채무", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00356361", 2025, "FY")
    assert confirmed["bs.trade_payables"] == 8_000_000_000


def test_trade_payables_additive_non_override_corp_unaffected():
    # 대조군: 등재 안 된 회사는 이 override 자체가 발동하지 않는다 — 두 라벨이 서로
    # 다른 canonical 에 각각 단일값으로 존재하면 override 없이도 각자 독립적으로
    # confirm 된다. bs.trade_payables 는 8B(단독) 그대로여야 하며, 형제 라벨과
    # 합산되면 안 된다.
    cands = {
        "bs.trade_payables": [
            _row(8_000_000_000, "exact", "매입채무", "부채>유동부채", node_role="F"),
        ],
        "bs.other_current_payables": [
            _row(2_000_000_000, "exact", "기타지급채무", "부채>유동부채", node_role="F"),
        ],
    }
    confirmed, conflicts = _resolve(cands, "00999999", 2025, "FY")
    assert confirmed["bs.trade_payables"] == 8_000_000_000


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
