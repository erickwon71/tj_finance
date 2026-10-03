"""R215 — SCE '결손금' balance cells take a NEGATIVE dated BS anchor; a negative combined BS
line '이익잉여금(결손금)' keys the '결손금' concept too.

`docs/PARSING_RULES.md` R215 (인투셀 `20260515002144` 2025 comparative block).
"""
from __future__ import annotations

import datetime

from fin2.extract.sce_dated_anchors import add_dated_anchors
from fin2.extract.sce_sign_repair import (
    apply_dated_balance_signs, build_sign_anchors, repair_sce_sign_loss,
)
from fin2.tests.test_sce_mirror_guard_r190 import _Line

_DEF, _CAP, _TOT = "자본>결손금", "자본>자본금", "자본>자본 합계"


def _row(label, row, deficit, cap, total):
    out = [_Line("SCE", "separate", label, deficit, col_index=0, col_label=_DEF, row_order=row)]
    if cap is not None:
        out.append(_Line("SCE", "separate", label, cap, col_index=1, col_label=_CAP, row_order=row))
    out.append(_Line("SCE", "separate", label, total, col_index=2, col_label=_TOT, row_order=row))
    return out


def _intocell_2025_block():
    """Balances printed as positive deficit magnitudes, movements already negative:
    1000 − 800 = 200 (opening), loss −30 → closing 1000 − 830 = 170."""
    return [
        *_row("2025.01.01 (기초자본)", 0, 800, 1000, 200),
        *_row("당기순이익(손실)", 1, -30, None, -30),
        *_row("2025.03.31 (기말자본)", 2, 830, 1000, 170),
    ]


def test_r215_combined_negative_bs_line_orients_the_deficit_block():
    # 인투셀 2025 block: BS '이익잉여금(결손금)' −800 / −830 now anchors the '결손금' column,
    # so the sign solve flips both balances and the block closes (−800 − 30 = −830).
    lines = _intocell_2025_block()
    prior = {datetime.date(2024, 12, 31): [("separate", "이익잉여금(결손금)", -800), ("separate", "자본총계", 200)],
             datetime.date(2025, 3, 31): [("separate", "이익잉여금(결손금)", -830), ("separate", "자본총계", 170)]}
    repair_sce_sign_loss(lines, prior)
    got = {ln.row_order: ln.value_won for ln in lines if ln.col_index == 0}
    assert got == {0: -800, 1: -30, 2: -830}


def test_r215_negative_deficit_anchor_flips_a_balance_when_the_block_improves():
    # The closing balance alone lost its sign: 기초 −800, loss −30, 기말 printed +830.
    lines = [
        *_row("2025.01.01 (기초자본)", 0, -800, 1000, 200),
        *_row("당기순이익(손실)", 1, -30, None, -30),
        *_row("2025.03.31 (기말자본)", 2, 830, 1000, 170),
    ]
    prior = {datetime.date(2025, 3, 31): [("separate", "결손금", -830), ("separate", "자본총계", 170)]}
    fixes = apply_dated_balance_signs(lines, prior)
    assert [(c.row_order, c.new_value) for c in fixes] == [(2, -830)]


def test_r215_deficit_column_printed_as_magnitudes_is_left_alone():
    # 20210323001020 shape: balances AND movements printed as positive magnitudes (the loss
    # increases the deficit +30). Flipping a balance alone would break the roll-forward.
    lines = [
        *_row("2025.01.01 (기초자본)", 0, 800, 1000, 200),
        *_row("당기순이익(손실)", 1, 30, None, -30),
        *_row("2025.03.31 (기말자본)", 2, 830, 1000, 170),
    ]
    prior = {datetime.date(2024, 12, 31): [("separate", "결손금", -800), ("separate", "자본총계", 200)],
             datetime.date(2025, 3, 31): [("separate", "결손금", -830), ("separate", "자본총계", 170)]}
    assert apply_dated_balance_signs(lines, prior) == []


def test_r215_combined_bs_label_keys_the_deficit_concept():
    lines = _intocell_2025_block()
    prior = {datetime.date(2024, 12, 31): [("separate", "이익잉여금(결손금)", -800),
                                           ("separate", "자본총계", 200)]}
    anchors = add_dated_anchors(build_sign_anchors(lines), lines, prior)
    assert anchors[("separate", "결손금", datetime.date(2024, 12, 31))] == {-800}


def test_r215_positive_combined_line_is_not_a_deficit():
    lines = _intocell_2025_block()
    prior = {datetime.date(2024, 12, 31): [("separate", "이익잉여금(결손금)", 800),
                                           ("separate", "자본총계", 200)]}
    anchors = add_dated_anchors(build_sign_anchors(lines), lines, prior)
    assert ("separate", "결손금", datetime.date(2024, 12, 31)) not in anchors
