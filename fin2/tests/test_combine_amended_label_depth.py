"""R2 델타패치 depth-우선 결함 회귀 테스트 (순수, DB 비의존).

docs/qa/gate_b_p3_depth_bug_2026-08-20.md.

build_merged_lines() 의 셀 키에 section_path 가 들어있어, 정정본이 표를 재렌더링해
section_path 가 원본과 달라지면(흔함 — 래퍼 한 겹 추가 등) 같은 항목의 두 셀이 "같은
셀의 수정"이 아니라 "다른 셀"로 살아남는다. 그러면 _reduce_conflict() 의 depth-우선이
section_path 가 얕은(=대개 원본) 쪽을 이겨버려, R2("정정이 이긴다")가 무력화된다.

실측: 고려아연(00102858) 2023FY 연결 — 원본 자산총계 12.046조가 2026-08-13 정정의
11.769조를 이겨버림. label_raw 가 각주번호까지 같이 바뀌는 경우도 있어("(5) 이익잉여금
(주27)" 원본 vs "(5) 이익잉여금" 정정본) norm() 정규화로 묶어야 한다.

_resolve() 는 amended=True(더 나중 필링에서 값이 바뀐 셀) 후보가 있으면, 같은
norm(label_raw) 의 amended=False(base) 후보를 depth 판정 전에 제거해야 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve  # noqa: E402


def _row(value, stage, label_raw, section_path, amended=False, amended_by=None):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "table_seq": 0,
            "amended": amended, "amended_by": amended_by}


def test_amended_deeper_section_path_wins_over_shallow_base():
    # 고려아연 2023FY 연결 자산총계 실측 재현.
    cands = {
        "bs.total_assets": [
            _row(12_046_071_311_650, "exact", "자산총계", "자산", amended=False),
            _row(11_768_590_335_824, "exact", "자산총계", "재무상태표 [개요]>자산",
                 amended=True, amended_by="20260813001690"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.total_assets"] == 11_768_590_335_824
    assert "bs.total_assets" not in conflicts


def test_amended_label_with_dropped_footnote_still_matches_via_norm():
    # "(5) 이익잉여금 (주27)" 원본 vs "(5) 이익잉여금" 정정본 — label_raw 완전일치가
    # 아니어도 norm() 으로 같은 항목임을 인식해야 한다.
    cands = {
        "bs.retained_earnings": [
            _row(7_843_381_808_493, "exact", "(5) 이익잉여금 (주27)",
                 "자본>I. 지배기업의 소유주에게 귀속되는 자본", amended=False),
            _row(7_569_848_258_924, "exact", "(5) 이익잉여금",
                 "재무상태표 [개요]>자본>I. 지배기업의 소유주에게 귀속되는 자본",
                 amended=True, amended_by="20260813001690"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.retained_earnings"] == 7_569_848_258_924


def test_no_amended_candidate_leaves_depth_priority_untouched():
    # amended 후보가 전혀 없으면(=진짜 같은 필링 안의 총계/하위항목 구조 차이) 손대지
    # 않는다 — 기존 depth-우선 동작(합계가 하위항목에 안 밀림)이 그대로 유지돼야 한다.
    cands = {
        "bs.total_assets": [
            _row(1_000, "exact", "자산총계", "자산"),
            _row(700, "exact", "유동자산", "자산>유동자산"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.total_assets"] == 1_000


def test_amended_wording_drift_wins_over_stale_exact_label():
    # 00103130(플레이그램) 2017 Q1 실측 재현 (docs/plans/
    # p3_1_trackd_failb_pattern_ab_fix_design_2026-08-20.md §1.3) — 정정본이 총계
    # 라벨을 "자산총계"(exact)→"자산"(fuzzy)로 통째로 바꿔 씀. norm() 은 이 둘을 같은
    # 그룹으로 못 묶으므로(단어 자체가 바뀜, 각주/공백 드리프트가 아님), _BS_GRAND_TOTAL
    # 3종은 라벨을 무시하고 canonical 전체를 한 그룹으로 취급해야 stale-drop 이 걸린다.
    cands = {
        "bs.total_assets": [
            _row(68_523_148_315, "exact", "자산총계", None, amended=False),
            _row(68_145_914_314, "fuzzy", "자산", None,
                 amended=True, amended_by="20180322000560"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.total_assets"] == 68_145_914_314
    assert "bs.total_assets" not in conflicts


def test_grand_total_wording_group_excludes_trust_account_rows():
    # trust_seqs 필터가 by_label(GRAND_TOTAL) 그룹핑보다 먼저 적용돼야 한다 — 안 그러면
    # 신탁계정의 amended 총계(자산==부채, table_seq 1)가 실제 재무제표의 총계와 같은
    # "라벨 무시" 그룹에 섞여 들어가 stage-rank 를 오염시킨다. 신탁계정 행이 먼저
    # 걸러지면 실제 재무제표의 amended 후보(950, fuzzy)가 그대로 채택돼야 한다.
    def _row2(value, stage, label_raw, table_seq, amended=False, amended_by=None):
        return {"value": value, "stage": stage, "label_raw": label_raw,
                "section_path": None, "table_seq": table_seq,
                "amended": amended, "amended_by": amended_by}

    cands = {
        "bs.total_assets": [
            _row2(1_000, "exact", "자산총계", 0, amended=False),
            _row2(950, "fuzzy", "자산", 0, amended=True, amended_by="X"),
            _row2(500, "exact", "신탁자산총계", 1, amended=True, amended_by="X"),
        ],
        "bs.total_liabilities": [
            _row2(500, "exact", "신탁부채총계", 1),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.total_assets"] == 950


def test_two_base_candidates_same_label_still_conflict_normally():
    # 둘 다 amended=False 인데 값이 갈리면(진짜 충돌) 기존 HOLD 동작이 유지돼야 한다 —
    # 이 수정이 "값이 다르면 무조건 하나를 고른다"로 퍼지면 안 된다.
    cands = {
        "bs.trade_payables": [
            _row(100, "exact", "매입채무", "부채>유동부채"),
            _row(200, "exact", "매입채무", "부채>유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert "bs.trade_payables" not in confirmed
    assert "bs.trade_payables" in conflicts
