"""R162 — SCE 원문에서 빠진 음수 괄호 복원 회귀 테스트.

실측 근거는 효성중공업 `20190515002585`(2019Q1). `docs/PARSING_RULES.md` R162.
"""
from __future__ import annotations

import inspect

import pytest

from fin2.extract.sce_sign_repair import (
    Correction,
    concept_of_col_label,
    repair_sce_sign_loss,
)


class _Line:
    """ReportLineRow 의 최소 대역 — 이 모듈이 읽는 속성만 갖는다."""

    def __init__(self, statement, basis, label_raw, value_won, *,
                 col_index=0, col_label=None, row_order=0, table_seq=0):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.col_label = col_label
        self.row_order = row_order
        self.table_seq = table_seq


def _hyosung_separate_lines():
    """효성중공업 별도 SCE + 앵커가 될 BS/IS 행(원문 그대로 = 부호 빠진 상태)."""
    lines = [
        # 앵커 — BS/IS 는 원문에 괄호가 있어 음수로 파싱된다.
        _Line("BS", "separate", "기타자본구성요소", -29_461_715_719),
        _Line("BS", "separate", "이익잉여금", 18_582_376_073),
        _Line("IS", "separate", "순확정급여부채의 재측정요소", -307_150_286),
    ]
    # SCE — 이익잉여금 열(c2)과 기타자본구성요소 열(c3)
    rows = [
        (0, "2019.01.01 (당기초)", {2: 15_091_684_311, 3: 30_162_524_009}),
        (1, "총포괄손익>당기순이익", {2: 3_797_842_048}),
        (2, "기타포괄손익-공정가치측정지분상품 평가손익", {3: 448_570}),
        (3, "순확정급여부채의 재측정요소", {2: 307_150_286}),
        (4, "해외사업환산손익", {3: 700_359_720}),
        (7, "2019.03.31 (당기말)", {2: 18_582_376_073, 3: 29_461_715_719}),
    ]
    col_labels = {2: "자본>이익잉여금", 3: "자본>기타자본구성요소"}
    for row_order, label, cells in rows:
        for col, value in cells.items():
            lines.append(_Line("SCE", "separate", label, value,
                               col_index=col, col_label=col_labels[col],
                               row_order=row_order))
    return lines


def _sce(lines, col_index, row_order):
    (found,) = [l for l in lines if l.statement == "SCE"
                and l.col_index == col_index and l.row_order == row_order]
    return found


# --------------------------------------------------------------------------
# 실측 사례 복원
# --------------------------------------------------------------------------

def test_restores_movement_cell_anchored_by_is():
    """IS 에 같은 라벨이 음수로 있는 변동행 — camp_run 이 보고한 바로 그 셀."""
    lines = _hyosung_separate_lines()
    fixes = repair_sce_sign_loss(lines)
    assert _sce(lines, 2, 3).value_won == -307_150_286
    assert any(f.col_index == 2 and f.row_order == 3 for f in fixes)


def test_restores_balance_cells_anchored_by_col_label():
    """잔액행은 label_raw 가 날짜다 — 개념은 col_label 에 있고 그것으로 앵커한다.

    ★기초 잔액은 BS 전기말과 대조해야 하는데 BS 는 col_index=0(당기)만 적재하므로
    DB 안에 짝이 없다. 라벨 교차대조만으로는 원리적으로 못 닿고, 항등식이 orientation
    을 이어받아 복원한다 — 이 테스트가 그 경로를 고정한다.
    """
    lines = _hyosung_separate_lines()
    repair_sce_sign_loss(lines)
    assert _sce(lines, 3, 7).value_won == -29_461_715_719   # 기말: BS 앵커 직접
    assert _sce(lines, 3, 0).value_won == -30_162_524_009   # 기초: 항등식으로만


def test_column_identities_close_after_repair():
    """복원 후 두 열 모두 기초+변동=기말 이 정확히 닫힌다."""
    lines = _hyosung_separate_lines()
    repair_sce_sign_loss(lines)
    for col, movements in ((2, (1, 3)), (3, (2, 4))):
        opening = _sce(lines, col, 0).value_won
        closing = _sce(lines, col, 7).value_won
        total = opening + sum(_sce(lines, col, r).value_won for r in movements)
        assert total == closing, f"c{col} 항등식 불일치"


def test_genuine_positive_movements_are_not_flipped():
    """★열 전체를 반전하지 않는다 — 기타자본 열의 변동행은 양수가 맞다.

    잔액만 괄호를 잃은 사례라, 일괄 부호반전으로 '고치면' 멀쩡한 변동행을 망친다.
    """
    lines = _hyosung_separate_lines()
    repair_sce_sign_loss(lines)
    assert _sce(lines, 3, 2).value_won == 448_570
    assert _sce(lines, 3, 4).value_won == 700_359_720
    assert _sce(lines, 2, 1).value_won == 3_797_842_048


def test_correction_names_its_anchor():
    """교정 내역은 근거(앵커 라벨)를 담는다 — 셀이 아니라 **블록** 기준."""
    lines = _hyosung_separate_lines()
    fixes = repair_sce_sign_loss(lines)
    assert fixes
    for fix in fixes:
        assert isinstance(fix, Correction)
        assert fix.anchor_label, f"{fix.label_raw}: 앵커 없이 교정됐다"
        assert abs(fix.old_value) == abs(fix.new_value)
        assert fix.old_value != fix.new_value


# --------------------------------------------------------------------------
# 손대지 않는 경우 (R6 — 오염보다 결측)
# --------------------------------------------------------------------------

def test_healthy_table_is_untouched():
    """항등식이 이미 닫히면 아무것도 바꾸지 않는다."""
    lines = [
        _Line("BS", "separate", "이익잉여금", 300),
        _Line("SCE", "separate", "2019.01.01 (당기초)", 100,
              col_index=0, col_label="자본>이익잉여금", row_order=0),
        _Line("SCE", "separate", "당기순이익", 200,
              col_index=0, col_label="자본>이익잉여금", row_order=1),
        _Line("SCE", "separate", "2019.12.31 (당기말)", 300,
              col_index=0, col_label="자본>이익잉여금", row_order=2),
    ]
    before = [l.value_won for l in lines]
    assert repair_sce_sign_loss(lines) == []
    assert [l.value_won for l in lines] == before


def test_no_anchor_means_no_repair():
    """앵커가 없으면 orientation 을 못 정한다 — mirror 배정이 늘 함께 성립하므로.

    항등식만으로는 (기초 −, 변동 +, 기말 −) 와 그 전체반전이 **둘 다** 만족한다.
    """
    lines = [
        _Line("SCE", "separate", "2019.01.01 (당기초)", 100,
              col_index=0, col_label="자본>기타자본구성요소", row_order=0),
        _Line("SCE", "separate", "평가손익", 30,
              col_index=0, col_label="자본>기타자본구성요소", row_order=1),
        _Line("SCE", "separate", "2019.12.31 (당기말)", 70,
              col_index=0, col_label="자본>기타자본구성요소", row_order=2),
    ]
    assert repair_sce_sign_loss(lines) == []
    assert [l.value_won for l in lines] == [100, 30, 70]


def test_ambiguous_solution_is_rejected():
    """여러 배정이 항등식을 만족하면 판정불가로 두고 손대지 않는다."""
    # 0 이 섞여 있어 그 셀의 부호가 어느 쪽이든 항등식이 성립한다.
    lines = [
        _Line("BS", "separate", "이익잉여금", 100),
        _Line("SCE", "separate", "2019.01.01 (당기초)", 100,
              col_index=0, col_label="자본>이익잉여금", row_order=0),
        _Line("SCE", "separate", "변동A", 50,
              col_index=0, col_label="자본>이익잉여금", row_order=1),
        _Line("SCE", "separate", "변동B", 50,
              col_index=0, col_label="자본>이익잉여금", row_order=2),
        _Line("SCE", "separate", "2019.12.31 (당기말)", 100,
              col_index=0, col_label="자본>이익잉여금", row_order=3),
    ]
    # +50-50 도, -50+50 도 항등식을 만족한다 → 두 배정 → 기각.
    assert repair_sce_sign_loss(lines) == []


def test_anchor_contradiction_means_no_repair():
    """앵커가 요구하는 부호로는 항등식이 닫히지 않으면 손대지 않는다."""
    lines = [
        _Line("BS", "separate", "이익잉여금", 999),   # 기말과 절대값이 다름
        _Line("SCE", "separate", "2019.01.01 (당기초)", 100,
              col_index=0, col_label="자본>이익잉여금", row_order=0),
        _Line("SCE", "separate", "변동", 7,
              col_index=0, col_label="자본>이익잉여금", row_order=1),
        _Line("SCE", "separate", "2019.12.31 (당기말)", 50,
              col_index=0, col_label="자본>이익잉여금", row_order=2),
    ]
    assert repair_sce_sign_loss(lines) == []


def test_source_negative_cells_are_not_candidates():
    """원문에 괄호가 있어 음수로 파싱된 셀은 추측 대상이 아니다.

    이 표는 기초를 뒤집으면 닫히지만(−100+30 = −70), 기초가 이미 음수라 후보가
    아니고 나머지로는 못 닫아 손대지 않는다.
    """
    lines = [
        _Line("BS", "separate", "기타자본구성요소", -70),
        _Line("SCE", "separate", "2019.01.01 (당기초)", -100,
              col_index=0, col_label="자본>기타자본구성요소", row_order=0),
        _Line("SCE", "separate", "평가손익", 50,
              col_index=0, col_label="자본>기타자본구성요소", row_order=1),
        _Line("SCE", "separate", "2019.12.31 (당기말)", -70,
              col_index=0, col_label="자본>기타자본구성요소", row_order=2),
    ]
    assert repair_sce_sign_loss(lines) == []
    assert lines[2].value_won == 50


def test_only_sce_is_modified():
    """BS/IS/CF 는 읽기만 한다 — 앵커 원본을 건드리면 안 된다."""
    lines = _hyosung_separate_lines()
    non_sce_before = [(l.statement, l.value_won) for l in lines
                      if l.statement != "SCE"]
    repair_sce_sign_loss(lines)
    non_sce_after = [(l.statement, l.value_won) for l in lines
                     if l.statement != "SCE"]
    assert non_sce_before == non_sce_after


def test_blocks_are_scoped_per_column_and_table():
    """서로 다른 열/표가 섞이면 항등식이 엉킨다 — 그룹 키에 셋 다 들어가야 한다."""
    src = inspect.getsource(repair_sce_sign_loss)
    assert "table_seq" in src and "col_index" in src and "ln.basis" in src


# --------------------------------------------------------------------------
# col_label 개념 추출
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("자본>기타자본구성요소", "기타자본구성요소"),
    ("자본 > 이익잉여금 ", "이익잉여금"),
    ("비지배지분", "비지배지분"),
    (None, ""),
    ("", ""),
])
def test_concept_of_col_label(raw, expected):
    """BS 라벨과 맞추려면 계층 접두어('자본>')를 떼고 마지막 조각만 쓴다."""
    assert concept_of_col_label(raw) == expected
