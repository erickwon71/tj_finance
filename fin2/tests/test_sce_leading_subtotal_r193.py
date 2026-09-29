"""R193 — SCE subtotals printed **above** their components are proven from the rows below.

`docs/PARSING_RULES.md` R193.
"""
from __future__ import annotations

from types import SimpleNamespace

import fin2.extract.sce_sign_repair as ssr
from fin2.extract.sce_sign_repair import _Cell, _proven_subtotals, _subtotal_fixes, repair_sce_sign_loss

_P, _F = SimpleNamespace(node_role="P"), SimpleNamespace(node_role="F")


def _cosmo_2011_total_column():
    """코스모화학 `20181005000496` 별도 합계 열 2011 블록 (headings carry the sum of the rows below)."""
    rows = (("2011.01.01(당기초)", 219778508527, _F),
            ("총포괄손익", 14271592742, _P),
            ("당기순이익", 14009755698, _F),
            ("기타포괄손익", 261837044, _P),
            ("- 매도가능금융자산평가이익", -162261500, _F),
            ("- 부의지분법자본변동", 424098544, _F),
            ("- 신주인수권부사채의발행", 7116445927, _F),
            ("- 신주인수권행사", 13656927612, _F),
            ("이익잉여금에 직접 반영된 거래 등", -385279004, _P),
            ("- 부의지분법이익잉여금변동", -385279004, _F),
            ("자본에 직접 반영된 소유주와의 거래 등", 318158750, _P),
            ("- 자기주식의 처분", 318158750, _F),
            ("2011.12.31(당기말)", 254756354554, _F))
    return [_Cell(line=ln, basis="separate", label_raw=l, col_label="합계", value=v) for l, v, ln in rows]


def test_r193_nested_leading_headings_are_proven_and_the_block_closes():
    cells = _cosmo_2011_total_column()
    move_i = list(range(1, 12))
    subs = _proven_subtotals(cells, move_i)
    assert sorted(subs) == [1, 3, 8, 10]
    total = cells[0].value + sum(cells[m].value for m in move_i if m not in subs)
    assert total == cells[-1].value
    assert _subtotal_fixes(cells, move_i, subs, {}) == []


def test_r193_switch_off_keeps_the_old_behaviour():
    cells = _cosmo_2011_total_column()
    ssr._LEADING_SUBTOTALS = False
    try:
        assert _proven_subtotals(cells, list(range(1, 12))) == []
    finally:
        ssr._LEADING_SUBTOTALS = True


def test_r193_a_plain_row_equal_to_the_next_is_not_a_heading():
    # Neither a subtotal label nor a parent row: two equal movements stay two movements.
    rows = (("기초", 1000, _F), ("자기주식의 취득", 300, _F), ("자기주식의 처분", 300, _F), ("기말", 1600, _F))
    cells = [_Cell(line=ln, basis="separate", label_raw=l, col_label="자본조정", value=v) for l, v, ln in rows]
    assert _proven_subtotals(cells, [1, 2]) == []


def test_r193_needs_the_printed_sign_below():
    # A component that lost its parenthesis breaks the signed sum: no guess.
    rows = (("기초", 1000, _F), ("기타포괄손익", 50, _P), ("- 평가이익", 80, _F), ("- 환산손실", 30, _F),
            ("기말", 1050, _F))
    cells = [_Cell(line=ln, basis="separate", label_raw=l, col_label="기타포괄손익누계액", value=v)
             for l, v, ln in rows]
    assert _proven_subtotals(cells, [1, 2, 3]) == []


class _Line:
    def __init__(self, label_raw, value_won, row_order, node_role="F"):
        self.statement, self.basis = "SCE", "separate"
        self.label_raw, self.value_won = label_raw, value_won
        self.col_index, self.col_label = 0, "자본>이익잉여금"
        self.row_order, self.table_seq = row_order, 0
        self.report_fiscal_period = "FY"
        self.node_role = node_role


def test_r193_leading_subtotal_out_of_the_sum_lets_the_single_flip_close():
    # '총포괄손익' above '당기순이익': summed twice, no single flip closes the block. With the
    # heading proven, the dividend that lost its parenthesis is the unique flip (R162-e).
    rows = (("2011.01.01(기초)", 1000, "F"), ("총포괄손익", 300, "P"), ("당기순이익", 300, "F"),
            ("배당금의 지급", 100, "F"), ("2011.12.31(기말)", 1200, "F"))
    lines = [_Line(l, v, i, r) for i, (l, v, r) in enumerate(rows)]
    repair_sce_sign_loss(lines, {})
    assert [ln.value_won for ln in lines] == [1000, 300, 300, -100, 1200]


def test_r193_trailing_total_after_two_leading_headings_is_proven():
    # 미원에스씨 `20260515000421` 별도 이익잉여금 2025 블록: '자본 증가(감소) 합계' sums the two
    # headings, not their rows as well.
    rows = (("2025.01.01 (기초자본)", 265478859151, _F), ("포괄손익", 15206823295, _P),
            ("당기순이익(손실)", 15206823295, _F), ("기타포괄손익-공정가치측정금융자산평가손익", 0, _F),
            ("자본에 직접 반영된 소유주와의 거래 등", -8765652600, _P), ("배당금지급", -8765652600, _F),
            ("자기주식의 취득", 0, _F), ("이익잉여금 전입", 0, _F),
            ("자본 증가(감소) 합계", 6441170695, _F), ("2025.03.31 (기말자본)", 271920029846, _F))
    cells = [_Cell(line=ln, basis="separate", label_raw=l, col_label="이익잉여금", value=v) for l, v, ln in rows]
    move_i = list(range(1, 9))
    subs = _proven_subtotals(cells, move_i)
    assert sorted(subs) == [1, 4, 8]
    assert cells[0].value + sum(cells[m].value for m in move_i if m not in subs) == cells[-1].value
    assert _subtotal_fixes(cells, move_i, subs, {}) == []


def test_r193_group_starting_at_a_heading_keeps_the_earlier_row_for_the_outer_total():
    # 미래에셋생명 `20250318001228` 별도 자본 합계 2023 블록: '총포괄손익' = 당기순이익 +
    # '총기타포괄손익', whose group starts at a heading. The block closes as printed.
    rows = (("기초자본_회계정책변경 및 오류수정 효과 반영", 2875241815354, _F),
            ("당기순이익(손실)", 109199854875, _F),
            ("기타포괄손익-공정가치측정금융자산관련손익 합계", 653331958330, _F),
            ("기타포괄손익-공정가치측정금융자산관련손익 총손익", 653331958330, _F),
            ("보험계약자산(부채)순금융손익", -759953049663, _F),
            ("재보험계약자산(부채)순금융손익", 2800822033, _F),
            ("현금흐름위험회피", 141688025440, _F),
            ("유형자산재평가잉여금", 2835, _F),
            ("확정급여제도의재측정요소", -3282093264, _F),
            ("총기타포괄손익", 34585665711, _F),
            ("총포괄손익", 143785520586, _F),
            ("기타변동", -272395, _F),
            ("소유주와의 거래 합계", -272395, _F),
            ("자본 증가(감소) 합계", 143785248191, _F),
            ("2023.12.31 (기말자본)", 3019027063545, _F))
    cells = [_Cell(line=ln, basis="separate", label_raw=l, col_label="자본 합계", value=v) for l, v, ln in rows]
    move_i = list(range(1, 14))
    subs = _proven_subtotals(cells, move_i)
    assert sorted(subs) == [2, 9, 10, 12, 13]
    assert cells[0].value + sum(cells[m].value for m in move_i if m not in subs) == cells[-1].value
    assert _subtotal_fixes(cells, move_i, subs, {}) == []
