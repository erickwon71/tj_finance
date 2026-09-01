"""Gate B Phase B line_audit 단위 테스트 — won_match 허용오차 + 라인 reconcile 분류.

★2026-09-01 계층2 GC §4-3 Phase 2 이식(fact_v2 acode 키 → report_lines 라벨 키) — 기존 12건
fixture 는 fact_v2 shape(acode/amount_won)라 전량 report_lines shape(label_raw/value_won)로
갱신. 신규: 라벨 정규화 경계·EPS 제외·in_body_section 배제·라벨 중복행 충돌·Track B
is_cumulative 비대상 회귀가드.

★2026-09-01 Phase 4(전수재감사) 실측 후속 수정 — Track B 매칭 키에 `statement` 복원
(최초 구현은 뺐다가 CF/SCE 동명이의 라벨 충돌로 대량 허위 VALUE_DIFF 유발을 실측으로
발견, `_track_b_key()` docstring 상세 근거). `_tface()` 헬퍼에 `stmt` 파라미터 추가,
회귀가드 2건(`test_trackb_cross_statement_label_not_confused`,
`test_trackb_sce_shadow_label_not_confused`) 신규.

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


def _face(acode, won, basis="consolidated", ade=0, cum=False, row_label=None, in_body=True):
    """Track A face 라인(acode 접두 ifrs/dart). adecimal<0 면 amount_won = won.
    여기선 amount_won 을 직접 통제하려 ade=0(=displayed) 사용. row_label 미지정 시 acode 를
    그대로 라벨로 씀(편의상 — 실제론 XBRL 라벨 텍스트)."""
    return FaceLine(statement=None, basis=basis, acode=acode, canonical=None,
                    label=acode, displayed_value=won, adecimal=ade, is_cumulative=cum,
                    row_label=row_label if row_label is not None else acode,
                    in_body_section=in_body)


def _lrow(label, won, basis="consolidated", cum=False, stmt="BS"):
    """report_lines 행(dict) — Track A 대조 대상."""
    return {"label_raw": label, "basis": basis, "is_cumulative": cum,
            "value_won": won, "statement": stmt}


def _tface(canon, won, basis="consolidated", ade=0, label=None, stmt="BS"):
    """Track B(텍스트) face 라인 — acode=라벨(비XBRL), canonical 매핑됨. `.label` 이 곧
    Track A 의 row_label 에 대응하는 라벨 원문(Track B 는 애초에 라벨 텍스트를 label 에 담음).
    `.statement` 는 `read_report_face_text()` 가 항상 채우는 값이라(BS/IS/CF 중 하나 확정)
    기본값을 둠 — None 이면 안 됨(매칭 키의 일부, 2026-09-01 Phase 4 실측 이후)."""
    lbl = label if label is not None else canon
    return FaceLine(statement=stmt, basis=basis, acode=lbl, canonical=canon,
                    label=lbl, displayed_value=won, adecimal=ade, is_cumulative=True)


def _tlrow(label, won, basis="consolidated", stmt="BS"):
    """report_lines 행(dict) — Track B 대조 대상. is_cumulative 는 Track B 매칭 키에 안 쓰이므로
    값 상관없이 False 고정(디폴트 BS 규약과 일치, 회귀 없음 확인용)."""
    return {"label_raw": label, "basis": basis, "is_cumulative": False,
            "value_won": won, "statement": stmt}


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
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계"),
            _face("dart_Revenue", 500, cum=True, row_label="매출액")]
    lines = [_lrow("자산총계", 1000), _lrow("매출액", 500, cum=True)]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 2 and r.n_match == 2
    assert r.n_value_diff == 0 and r.n_missing == 0 and r.n_extra == 0
    assert r.line_gate_status == "pass"


def test_reconcile_value_diff():
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계")]
    lines = [_lrow("자산총계", 1234)]   # >tol 차이
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_value_diff == 1 and r.n_match == 0
    assert r.value_diffs[0].reason == REASON_VALUE_DIFF
    assert r.value_diffs[0].report_won == 1000 and r.value_diffs[0].db_won == 1234
    assert r.value_diffs[0].acode == "ifrs-full_Assets"   # 진단용 필드 보존
    assert r.line_gate_status == "fail_a"


def test_reconcile_missing_in_db():
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계"),
            _face("dart_Foo", 7, row_label="기타계정")]
    lines = [_lrow("자산총계", 1000)]    # "기타계정" 이 report_lines 에 없음
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_missing == 1 and r.n_match == 1
    assert r.missing[0].reason == REASON_MISSING and r.missing[0].label == "기타계정"
    assert r.line_gate_status == "pass"          # missing 은 차단 아님(측정 우선)


def test_reconcile_extra_in_db():
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계")]
    lines = [_lrow("자산총계", 1000), _lrow("잉여계정", 9)]   # DB 잉여
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_extra == 1 and r.n_match == 1 and r.n_value_diff == 0


def test_basis_distinguished():
    # 같은 라벨이라도 basis 다르면 별개 라인
    face = [_face("ifrs-full_Assets", 1000, basis="consolidated", row_label="자산총계"),
            _face("ifrs-full_Assets", 800, basis="separate", row_label="자산총계")]
    lines = [_lrow("자산총계", 1000, basis="consolidated"),
             _lrow("자산총계", 800, basis="separate")]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 2 and r.n_match == 2 and r.n_value_diff == 0


def test_text_supplement_lines_ignored():
    # acode 가 XBRL 접두 아닌 라인(텍스트 보충)은 Track A 대조 대상 아님 → 미집계
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계"), FaceLine(
        statement="IS", basis="consolidated", acode="매출액", canonical="is.revenue",
        label="매출액", displayed_value=500, adecimal=0, row_label="매출액")]
    lines = [_lrow("자산총계", 1000), _lrow("매출액", 500, stmt="IS")]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 1 and r.n_match == 1   # 텍스트 라인 제외
    assert r.n_missing == 0


def test_eps_lines_excluded():
    # §3-3 실측 오탐 클러스터(EPS/주식수) — Track A 대조 대상에서 제외.
    face = [_face("ifrs-full_Assets", 1000, row_label="자산총계"),
            _face("ifrs-full_BasicEarningsLossPerShare", 151, row_label="기본주당이익"),
            _face("ifrs-full_NumberOfSharesIssued", 999, row_label="발행주식수")]
    lines = [_lrow("자산총계", 1000), _lrow("기본주당이익", 151_000), _lrow("발행주식수", 1)]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 1   # EPS/주식수 두 줄 모두 제외, 자산총계만 남음
    assert r.n_match == 1 and r.n_value_diff == 0


def test_in_body_section_false_excluded_none_passes():
    # in_body_section=False(주석표 확정) 만 배제, None(판정불가)은 통과(결측>오탐).
    face = [_face("ifrs-full_Assets", 1000, row_label="재고자산", in_body=False),
            _face("dart_Revenue", 500, row_label="사용권자산", in_body=None)]
    lines = [_lrow("재고자산", 1000), _lrow("사용권자산", 500)]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 1   # False 만 배제
    assert r.n_match == 1


def test_basis_none_notes_cells_excluded():
    # basis=None(주석 컨텍스트, 다중셀 동일태그) 라인은 본문 대조 대상 아님 → 미집계.
    face = [_face("ifrs-full_Revenue", 892359, basis="consolidated", row_label="매출액"),
            _face("ifrs-full_Revenue", 227701, basis=None, row_label="매출액")]   # 주석 셀
    lines = [_lrow("매출액", 892359, basis="consolidated"),
             _lrow("매출액", 300000, basis=None)]   # 주석 셀(또 다른 값)
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 1 and r.n_match == 1          # 본문(연결)만 대조
    assert r.n_value_diff == 0 and r.n_extra == 0     # 주석 셀 충돌 무시


def test_label_normalization_whitespace():
    # 공백만 다른 라벨(전각/반각 공백 포함)은 같은 라인으로 매칭돼야 함.
    face = [_face("ifrs-full_Assets", 1000, row_label="현금 및  현금성자산")]
    lines = [_lrow("현금및현금성자산", 1000)]
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_lines == 1 and r.n_match == 1 and r.n_missing == 0


def test_label_duplicate_row_collision_first_wins():
    # report_lines 쪽에 같은 (basis,라벨) 이 중복되면(coarse 키 충돌) 첫 등장이 대표값 —
    # 구 acode 키 시절의 first-wins 규약을 그대로 보존.
    face = [_face("ifrs-full_Assets", 1000, row_label="계")]
    lines = [_lrow("계", 1000), _lrow("계", 9999)]   # 두 번째는 무시돼야 함
    r = reconcile_report_lines("R1", face, lines)
    assert r.n_match == 1 and r.n_value_diff == 0


def test_trackb_current_value_in_report_set():
    # 보고서는 당기+전기 컬럼(리터럴 다수), report_lines 당기값이 그 집합에 있으면 match.
    face = [_tface("bs.total_assets", 1000, label="자산총계"),
            _tface("bs.total_assets", 800, label="자산총계")]  # 당기/전기
    lines = [_tlrow("자산총계", 1000)]   # DB 당기값
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_lines == 1 and r.n_match == 1 and r.n_value_diff == 0


def test_trackb_value_diff():
    # DB 당기값이 보고서 어느 컬럼에도 없음 → 손상 후보(차단).
    face = [_tface("is.revenue", 500, label="매출액", stmt="IS"),
            _tface("is.revenue", 400, label="매출액", stmt="IS")]
    lines = [_tlrow("매출액", 777, stmt="IS")]
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_value_diff == 1 and r.n_match == 0
    assert r.value_diffs[0].reason == REASON_VALUE_DIFF and r.value_diffs[0].db_won == 777
    assert r.value_diffs[0].canonical == "is.revenue"   # 진단용 필드 보존


def test_trackb_cross_statement_label_not_confused():
    # ★2026-09-01 Phase 4 전수재감사 실측으로 발견한 실버그의 회귀가드 — CF 간접법
    # 조정 섹션은 IS 와 같은 라벨("금융비용" 등)을 재사용하지만 값은 다르다(조정액 vs
    # 원 손익). statement 를 매칭 키에서 빼면 IS 쪽 face 값이 CF 쪽 report_lines 값의
    # "정답 후보"로 잘못 취급돼 허위 VALUE_DIFF 가 났다(개선 4,151 : 악화 74,220 실측).
    face = [_tface("is.finance_cost", 100, label="금융비용", stmt="IS")]   # IS 원 손익
    lines = [_tlrow("금융비용", 100, stmt="IS"),      # IS 쪽은 그대로 일치
             _tlrow("금융비용", 930, stmt="CF")]       # CF 조정액(다른 값) — IS 후보와 무관해야
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_match == 1                 # IS 라인만 매칭
    assert r.n_value_diff == 0            # CF 라인이 IS 값과 비교돼 허위 VALUE_DIFF 나면 안 됨
    assert r.n_missing == 1               # CF 라인은 대응하는 face 가 없어 MISSING(비차단)이 정상
    assert r.missing[0].statement == "CF"


def test_trackb_sce_shadow_label_not_confused():
    # SCE(자본변동표) 는 report_lines 에 라벨이 같아도 col_index 의미가 다른 별도
    # statement 다(scripts/gateb_audit.py 가 SQL 에서 SCE 자체를 걸러내지만, line_audit.py
    # 매칭 로직만으로도 안전해야 한다는 방어선 확인). 같은 라벨의 SCE 행이 섞여 들어와도
    # IS 매칭에 영향을 주면 안 됨.
    face = [_tface("is.net_income", 1000, label="당기순이익(손실)", stmt="IS")]
    lines = [_tlrow("당기순이익(손실)", 1000, stmt="IS"),
             _tlrow("당기순이익(손실)", 0, stmt="SCE")]   # SCE 자본금 컬럼 등 무관 값(전형 0)
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_match == 1 and r.n_value_diff == 0
    assert r.n_missing == 1 and r.missing[0].statement == "SCE"


def test_trackb_missing_when_reader_absent():
    # report_lines 에 있는 라벨을 리더가 보고서에서 못 찾음 → MISSING(커버 갭, 비차단).
    face = [_tface("bs.total_assets", 1000, label="자산총계")]
    lines = [_tlrow("자산총계", 1000), _tlrow("영업활동현금흐름", 300, stmt="CF")]
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_match == 1 and r.n_missing == 1
    assert r.missing[0].reason == REASON_MISSING


def test_trackb_line_row_without_value_skipped():
    # value_won=None(단위 미확정 등) report_lines 행은 대조 불가 → 집계 제외.
    face = [_tface("bs.total_assets", 1000, label="자산총계")]
    lines = [_tlrow("자산총계", 1000), {"label_raw": "미확정계정", "basis": "consolidated",
                                        "is_cumulative": False, "value_won": None, "statement": "BS"}]
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_lines == 1 and r.n_match == 1


def test_trackb_basis_distinguished():
    face = [_tface("bs.total_assets", 1000, basis="consolidated", label="자산총계"),
            _tface("bs.total_assets", 800, basis="separate", label="자산총계")]
    lines = [_tlrow("자산총계", 1000, basis="consolidated"),
             _tlrow("자산총계", 800, basis="separate")]
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_lines == 2 and r.n_match == 2 and r.n_value_diff == 0


def test_trackb_is_cumulative_not_in_key():
    # ★회귀가드: read_report_face_text() 는 is_cumulative 를 항상 True 로 채우는 placeholder라
    # (실제 축 아님), report_lines 쪽 실제 is_cumulative(BS=False)와 안 맞아도 매칭돼야 한다.
    face = [_tface("bs.total_assets", 1000, label="자산총계")]   # FaceLine.is_cumulative=True 고정
    lines = [_tlrow("자산총계", 1000)]   # is_cumulative=False(BS 규약)
    r = reconcile_report_lines_text("R1", face, lines)
    assert r.n_match == 1 and r.n_missing == 0


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
