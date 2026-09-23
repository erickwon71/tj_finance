"""R162 — SCE 원문에서 빠진 음수 괄호 복원 회귀 테스트.

실측 근거는 효성중공업 `20190515002585`(2019Q1). `docs/PARSING_RULES.md` R162.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

from fin2.extract.sce_sign_repair import (
    Correction,
    apply_manual_sign_fixes,
    concept_of_col_label,
    repair_sce_sign_loss,
)

_ROOT = Path(__file__).resolve().parents[2]


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


# --------------------------------------------------------------------------
# R162-b — 이월잔액 앵커(전기 비교 블록)
# --------------------------------------------------------------------------

def _two_block_lines():
    """전기 블록 + 당기 블록. BS 는 **당기만** 적재하므로 전기엔 앵커가 없다.

    기타자본 열(실측 엠케이전자 `20150515000634` 구조):
        전기: 기초 100 → 배당 30 → 기말 70      (전부 괄호 유실)
        당기: 기초  70 → 배당 20 → 기말 50      (전부 괄호 유실)
    참값은 전부 음수다. BS 는 당기말 −50 만 갖고 있다.
    """
    col = "자본>기타자본구성요소"
    lines = [_Line("BS", "separate", "기타자본구성요소", -50)]
    rows = [
        (0, "2018.01.01 (전기초)", 100),
        (1, "배당", 30),
        (2, "2018.12.31 (전기말)", 70),
        (3, "2019.01.01 (당기초)", 70),
        (4, "배당", 20),
        (5, "2019.12.31 (당기말)", 50),
    ]
    for row_order, label, value in rows:
        lines.append(_Line("SCE", "separate", label, value,
                           col_index=0, col_label=col, row_order=row_order))
    return lines


def test_prior_year_block_is_reached_via_carried_balance():
    """당기 블록이 BS 로 풀리면 그 기초가 전기 블록의 기말 앵커가 된다.

    ★BS 는 col_index=0(당기)만 적재하므로 전기 블록에는 라벨 앵커가 원리적으로
    없다. 한 블록의 기말은 다른 블록의 기초와 **같은 잔액 그 자체**라 부호를
    물려받을 수 있다 — 이게 없으면 전기 블록이 영원히 틀린 채 남는다.
    """
    lines = _two_block_lines()
    repair_sce_sign_loss(lines)
    got = [l.value_won for l in lines if l.statement == "SCE"]
    assert got == [-100, 30, -70, -70, 20, -50]


def test_carried_balance_only_anchors_balance_rows():
    """이월잔액 앵커는 **잔액행에만** 쓴다 — 변동행까지 절대값으로 맞추면 날조된다."""
    src = inspect.getsource(
        sys.modules["fin2.extract.sce_sign_repair"]._required_sign)
    assert "_is_balance_label(cell.label_raw)" in src


def test_conflicting_carried_magnitude_is_dropped():
    """같은 절대값의 확정 잔액이 부호가 엇갈리면 그 절대값은 앵커로 쓰지 않는다."""
    from fin2.extract.sce_sign_repair import _carried_balance_signs, _Cell

    def cell(label, value):
        return _Cell(line=None, basis="separate", label_raw=label,
                     col_label=None, value=value)

    cells = [cell("2018.01.01 (전기초)", 100), cell("변동", 0),
             cell("2018.12.31 (전기말)", -100), cell("변동", 0),
             cell("2019.12.31 (당기말)", 55)]
    blocks = [(0, [1], 2), (2, [3], 4)]
    carried = _carried_balance_signs(cells, blocks, pending=[])
    assert 100 not in carried          # +100 과 −100 이 충돌 → 버린다
    assert carried.get(55) == 1


# --------------------------------------------------------------------------
# R162-c — 소계 행 이중계상 제외
# --------------------------------------------------------------------------

def _subtotal_lines(subtotal_label="총포괄손익", subtotal_value=15_354_023):
    """실측 디에이치엑스컴퍼니 `20150515000944` 연결 기타포괄손익누계액 열.

    구성요소 2행 뒤에 그 합이 **형제로** 한 줄 더 찍힌다. Σ변동에 같이 넣으면
    이중계상돼 항등식이 절대 닫히지 않는다.
    """
    col = "자본>기타포괄손익누계액"
    rows = [
        (0, "2013.01.01 (기초자본)", 127_312_821),
        (3, "지분법기타포괄손익", 21_360_989),
        (4, "매도가능증권평가손익", -6_006_966),
        (6, subtotal_label, subtotal_value),
        (8, "2013.12.31 (기말자본)", 142_666_844),
    ]
    lines = [_Line("BS", "consolidated", "기타포괄손익누계액", 142_666_844)]
    for row_order, label, value in rows:
        lines.append(_Line("SCE", "consolidated", label, value,
                           col_index=0, col_label=col, row_order=row_order))
    return lines


def test_subtotal_row_is_excluded_from_the_sum():
    """소계를 Σ변동에서 빼면 항등식이 닫힌다 — 그러면 고칠 것이 없다.

    ★이게 없으면 이 열은 영원히 '안 닫힘'으로 남아 같은 표의 다른 결함도 못 고친다.
    127,312,821 + 21,360,989 − 6,006,966 = 142,666,844 (소계 15,354,023 제외)
    """
    lines = _subtotal_lines()
    assert repair_sce_sign_loss(lines) == []
    assert [l.value_won for l in lines if l.statement == "SCE"] == [
        127_312_821, 21_360_989, -6_006_966, 15_354_023, 142_666_844]


def test_subtotal_own_sign_is_fixed_from_its_components():
    """소계는 Σ에서 빠져 항등식이 부호를 안 정해 준다 — 구성요소의 합으로 확정한다.

    구성요소 합이 −15,354,023 이면 소계도 그 부호여야 한다(추측이 아니다).
    """
    lines = _subtotal_lines(subtotal_value=15_354_023)
    sce = [l for l in lines if l.statement == "SCE"]
    sce[1].value_won = -21_360_989      # 지분법 −
    sce[2].value_won = 6_006_966        # 매도가능 +
    sce[0].value_won = 142_666_844      # 기초/기말을 맞춰 항등식은 닫히게 둔다
    sce[4].value_won = 127_312_821
    fixes = repair_sce_sign_loss(lines)
    assert sce[3].value_won == -15_354_023
    assert any(f.anchor_label == "소계=구성요소 합" for f in fixes)


def test_subtotal_needs_both_label_and_arithmetic():
    """★라벨만·산술만으로는 안 된다 — 둘 다 요구한다.

    실측에서 '당기순이익(손실)'·'해외사업환산손익'·'감자차손보전' 처럼 소계가 아닌
    행이 앞 구간의 합과 절대값이 같아 걸렸다. 산술만 믿으면 멀쩡한 변동행이 Σ에서
    빠져 항등식이 거짓으로 닫힌다.
    """
    from fin2.extract.sce_sign_repair import _proven_subtotals, _Cell

    def cell(label, value):
        return _Cell(line=None, basis="consolidated", label_raw=label,
                     col_label=None, value=value)

    # 산술은 맞지만 라벨이 소계가 아니다 → 소계로 보지 않는다.
    cells = [cell("지분법기타포괄손익", 10), cell("매도가능증권평가손익", 5),
             cell("해외사업환산손익", 15)]
    assert _proven_subtotals(cells, [0, 1, 2]) == []

    # 라벨은 소계지만 산술이 안 맞는다 → 소계로 보지 않는다.
    cells = [cell("지분법기타포괄손익", 10), cell("매도가능증권평가손익", 5),
             cell("총포괄손익", 99)]
    assert _proven_subtotals(cells, [0, 1, 2]) == []

    # 둘 다 맞다 → 소계.
    cells = [cell("지분법기타포괄손익", 10), cell("매도가능증권평가손익", 5),
             cell("총포괄손익 소계", 15)]
    assert _proven_subtotals(cells, [0, 1, 2]) == [2]


def test_single_component_subtotal_is_allowed():
    """구성요소가 1개인 소계도 정당하다('총포괄손익' 아래 '당기순이익' 하나).

    실측에서 흔하다 — 구성요소 2개 이상을 요구하면 진짜 소계를 놓친다.
    """
    from fin2.extract.sce_sign_repair import _proven_subtotals, _Cell

    cells = [_Cell(line=None, basis="c", label_raw="당기순이익",
                   col_label=None, value=200),
             _Cell(line=None, basis="c", label_raw="총포괄손익",
                   col_label=None, value=200)]
    assert _proven_subtotals(cells, [0, 1]) == [1]


def test_node_role_is_not_used_for_subtotals():
    """★들여쓰기(node_role='P')로는 소계를 못 찾는다 — 실측 0건으로 기각된 가설.

    문제의 표들은 모든 행이 depth=0·node_role='F' 다(원문에 들여쓰기가 없다).
    이 테스트는 판정이 산술+라벨로 이뤄진다는 계약을 고정한다.
    """
    src = inspect.getsource(
        sys.modules["fin2.extract.sce_sign_repair"]._proven_subtotals)
    # docstring 은 기각된 가설을 설명하느라 node_role 을 언급한다 — **코드**가
    # 그것을 읽지 않는다는 것만 검사한다(속성 접근이 없어야 한다).
    assert ".node_role" not in src
    assert "_SUBTOTAL_LABEL_RE" in src


def test_subtotal_exclusion_enables_a_repair_that_is_otherwise_impossible():
    """소계를 빼야 비로소 풀리는 블록 — 이 테스트가 R162-c 의 실제 가치를 고정한다.

    기초가 괄호를 잃은 표다. 소계('총포괄손익' = 구성요소 합)를 Σ에 그대로 두면 어떤
    부호 배정으로도 항등식이 닫히지 않아 기각된다. 소계를 빼면 유일한 배정이 나온다:

        −100 + 10 − 5 = −95   (기말은 BS 앵커로 음수 확정)
    """
    col = "자본>기타포괄손익누계액"
    lines = [_Line("BS", "consolidated", "기타포괄손익누계액", -95)]
    for row_order, label, value in [
        (0, "2013.01.01 (기초자본)", 100),      # 참값 −100 (괄호 유실)
        (1, "지분법기타포괄손익", 10),
        (2, "매도가능증권평가손익", -5),
        (3, "총포괄손익", 5),                    # = 10 + (−5) → 소계
        (4, "2013.12.31 (기말자본)", -95),
    ]:
        lines.append(_Line("SCE", "consolidated", label, value,
                           col_index=0, col_label=col, row_order=row_order))

    fixes = repair_sce_sign_loss(lines)
    sce = [l for l in lines if l.statement == "SCE"]
    assert sce[0].value_won == -100, "소계를 빼야 이 복원이 가능하다"
    assert any(f.row_order == 0 for f in fixes)
    # 소계와 구성요소는 건드리지 않는다
    assert [l.value_won for l in sce[1:4]] == [10, -5, 5]


# --------------------------------------------------------------------------
# R162-manual — 개별 확정 (issue#38, 2026-09-23)
# --------------------------------------------------------------------------

def test_manual_fix_flips_the_registered_cell():
    """SK텔레콤 20210517001554 — BS 에 '자기주식' 단독 행이 없어 일반 알고리즘의
    (가)앵커가 원리적으로 없다. 사용자가 개별 승인한 rcept 예외목록으로만 뒤집힌다.
    """
    line = _Line("SCE", "separate", "2021.03.31 (기말자본)", 2_169_660_000_000,
                 col_index=6, col_label="자본>기타불입자본>자기주식", row_order=17)
    fixes = apply_manual_sign_fixes([line], "20210517001554")
    assert line.value_won == -2_169_660_000_000
    assert len(fixes) == 1
    assert fixes[0].old_value == 2_169_660_000_000
    assert fixes[0].new_value == -2_169_660_000_000


def test_manual_fix_is_scoped_to_its_rcept():
    line = _Line("SCE", "separate", "2021.03.31 (기말자본)", 2_169_660_000_000,
                 col_index=6, col_label="자본>기타불입자본>자기주식", row_order=17)
    fixes = apply_manual_sign_fixes([line], "99999999999999")
    assert line.value_won == 2_169_660_000_000
    assert fixes == []


def test_manual_fix_requires_the_old_value_to_match():
    """★원문/코드가 달라져 값이 이미 다르면 조용히 덮지 않는다(R6)."""
    line = _Line("SCE", "separate", "2021.03.31 (기말자본)", 999,
                 col_index=6, col_label="자본>기타불입자본>자기주식", row_order=17)
    fixes = apply_manual_sign_fixes([line], "20210517001554")
    assert line.value_won == 999
    assert fixes == []


def test_manual_fix_is_wired_into_extract_report_lines():
    rl = (_ROOT / "fin2/extract/report_lines.py").read_text(encoding="utf-8")
    assert "apply_manual_sign_fixes(lines, rcept_no)" in rl
