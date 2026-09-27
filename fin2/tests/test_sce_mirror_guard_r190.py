"""R190 — SCE mirror-solution guard: interim BS dated anchors (G-A), note-ref BS labels,
and balance rows that prove their own printed signs (G-B(i)).

`docs/PARSING_RULES.md` R190, `docs/plans/sce_mirror_guard_design_2026-09-27.md`.
"""
from __future__ import annotations

import datetime

from fin2.extract.sce_dated_anchors import add_dated_anchors
from fin2.extract.sce_sign_repair import (
    _Cell, _required_sign, add_row_proven_anchors, build_sign_anchors, repair_sce_sign_loss,
)


class _Line:
    def __init__(self, statement, basis, label_raw, value_won, *, col_index=0,
                 col_label=None, row_order=0, table_seq=0, period="Q3"):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.col_label = col_label
        self.row_order = row_order
        self.table_seq = table_seq
        self.report_fiscal_period = period


_OTHER, _CAP, _TOT = "자본>기타자본구성요소", "자본>자본금", "자본>자본 합계"


def _sce_row(label, row, other, cap, total):
    out = []
    for ci, (col, v) in enumerate(((_OTHER, other), (_CAP, cap), (_TOT, total))):
        if v is not None:
            out.append(_Line("SCE", "separate", label, v, col_index=ci, col_label=col, row_order=row))
    return out


def _spurious_bracket_filing(bs_total=1020):
    """제닉스로보틱스 `20241114000214` shape. 기타자본구성요소: −100 + 100 − 20 = −20, but the
    closing is printed +20 — the movement '주식매수선택권' carries a spurious parenthesis
    (the truth is +20). The closing row adds up as printed: 20 + 1000 = 1020 = BS 자본총계."""
    return [
        *_sce_row("2024.01.01 (기초자본)", 0, -100, 1000, 900),
        *_sce_row("자기주식의 처분", 1, 100, None, 100),
        *_sce_row("주식매수선택권", 2, -20, None, -20),
        *_sce_row("2024.09.30 (기말자본)", 3, 20, 1000, 1020),
        _Line("BS", "separate", "자본총계", bs_total, col_index=0),
    ]


def _closing_other(lines):
    return next(ln for ln in lines if ln.statement == "SCE" and ln.row_order == 3 and ln.col_index == 0)


def test_row_proven_balance_rejects_the_mirror_flip():
    lines = _spurious_bracket_filing()
    fixes = repair_sce_sign_loss(lines)
    assert _closing_other(lines).value_won == 20
    assert not [c for c in fixes if c.row_order == 3 and c.col_index == 0]


def test_row_proof_needs_the_bs_equity_total():
    # 디알텍 `20210817000039` shape: the printed total is off from the BS, so the row proves
    # nothing and the column's own single-flip solution stands.
    lines = _spurious_bracket_filing(bs_total=999)
    repair_sce_sign_loss(lines)
    assert _closing_other(lines).value_won == -20


def test_row_proof_needs_the_row_identity_to_hold_as_printed():
    lines = _spurious_bracket_filing()
    _closing_other(lines).value_won = 30          # 30 + 1000 ≠ 1020
    anchors = add_row_proven_anchors(add_dated_anchors(build_sign_anchors(lines), lines), lines)
    assert ("separate", "기타자본구성요소", datetime.date(2024, 9, 30)) not in anchors


def test_note_ref_bs_label_anchors_the_column_concept():
    # 넵튠 `20210817001798`: BS '자본금 (주20)' vs SCE column '자본금'.
    lines = [
        *_sce_row("2020.01.01 (기초자본)", 0, None, 500, 500),
        *_sce_row("2020.06.30 (기말자본)", 1, None, 500, 500),
    ]
    prior = {datetime.date(2020, 6, 30): [("separate", "자본금 (주20)", 500),
                                          ("separate", "자본총계", 500)]}
    anchors = add_dated_anchors(build_sign_anchors(lines), lines, prior)
    ln = lines[2]                                 # 2020.06.30 자본금
    cell = _Cell(line=ln, basis=ln.basis, label_raw=ln.label_raw, col_label=ln.col_label,
                 value=ln.value_won)
    assert _required_sign(cell, anchors) == (1, "자본금@2020-06-30")


def test_interim_prior_balance_proves_a_comparative_block():
    # 씨에스베어링 `20220516002123` shape: 2021 comparative block printed without parentheses;
    # the 2021 Q1 report's BS (an interim date) proves the closing sign, so the block closes
    # with the stock-option movement kept positive.
    lines = [
        *_sce_row("2021.01.01 (기초자본)", 0, 4070, 5000, 930),
        *_sce_row("주식선택권", 1, 3, None, 3),
        *_sce_row("2021.03.31 (기말자본)", 2, 4067, 5000, 933),
    ]
    prior = {datetime.date(2020, 12, 31): [("separate", "기타자본구성요소", -4070), ("separate", "자본총계", 930)],
             datetime.date(2021, 3, 31): [("separate", "기타자본구성요소", -4067), ("separate", "자본총계", 933)]}
    repair_sce_sign_loss(lines, prior)
    got = {ln.row_order: ln.value_won for ln in lines if ln.col_index == 0}
    assert got == {0: -4070, 1: 3, 2: -4067}


def test_r190b_anchored_solution_must_stay_consistent_with_its_subtotal():
    # LB인베스트먼트 `20260318000708` shape: the opening is a typo (= the closing), the
    # dividend lost its parenthesis so '자본 증가(감소) 합계' (79 = −46 + 124 + 1) is not
    # proven and gets summed. No single flip closes the block. With the closing row anchored
    # (row holds, total = BS 자본총계), "dividend −, subtotal −" would close it; after that
    # flip the subtotal is proven and the block no longer closes → rejected. IS anchors fix
    # the NI/OCI signs, which leaves that one solution.
    re_, tot = "자본>이익잉여금", _TOT
    lines = []
    for row, (label, v) in enumerate((("2025.01.01 (기초자본)", 1270), ("연차배당", 46),
                                      ("당기순이익(손실)", 124), ("기타포괄손익", 1),
                                      ("자본 증가(감소) 합계", 79), ("2025.12.31 (기말자본)", 1270))):
        for ci, col in enumerate((re_, tot)):
            lines.append(_Line("SCE", "separate", label, v, col_index=ci, col_label=col, row_order=row))
    lines += [_Line("BS", "separate", "자본총계", 1270, col_index=0),
              _Line("IS", "separate", "당기순이익(손실)", 124, col_index=0),
              _Line("IS", "separate", "기타포괄손익", 1, col_index=0)]
    repair_sce_sign_loss(lines)
    got = {(ln.row_order, ln.col_index): ln.value_won for ln in lines if ln.statement == "SCE"}
    assert got[(4, 0)] == 79 and got[(4, 1)] == 79


def test_r190c_nested_subtotals_are_proven():
    # 미래에셋생명 `20240320002014` shape: an inner subtotal (−2054 + 2064 = 10), then
    # '소유주와의 거래 합계' = 10 + 347 and '자본 증가(감소) 합계' repeating it. The balances lost
    # their parentheses (BS: −3716 → −3712). With both outer subtotals proven, the anchored
    # solve flips the balances and keeps the movements positive.
    from fin2.extract.sce_sign_repair import _Cell as C, _proven_subtotals
    adj = "자본>자본조정"
    rows = (("2022.01.01 (기초자본)", 3716), ("자기주식의 취득", -2054), ("자기주식의 처분", 2064),
            ("자기주식 거래에 따른 증가(감소) 합계", 10), ("기타변동", 347),
            ("소유주와의 거래 합계", 357), ("자본 증가(감소) 합계", 357), ("2022.12.31 (기말자본)", 3359))
    cells = [C(line=None, basis="separate", label_raw=l, col_label=adj, value=v) for l, v in rows]
    assert _proven_subtotals(cells, list(range(1, 7))) == [3, 5, 6]

    lines = [_Line("SCE", "separate", l, v, col_index=0, col_label=adj, row_order=i)
             for i, (l, v) in enumerate(rows)]
    prior = {datetime.date(2022, 12, 31): [("separate", "자본조정", -3359), ("separate", "자본총계", -3359)]}
    lines += [_Line("SCE", "separate", rows[0][0], 3716, col_index=1, col_label=_TOT, row_order=0),
              _Line("SCE", "separate", rows[7][0], -3359, col_index=1, col_label=_TOT, row_order=7)]
    repair_sce_sign_loss(lines, prior)
    got = {ln.row_order: ln.value_won for ln in lines if ln.col_index == 0}
    assert got[0] == -3716 and got[7] == -3359 and got[5] == 357 and got[6] == 357


def test_r190c_nested_subtotal_signs_follow_the_inner_subtotal():
    # 미래에셋생명 주식발행초과금 2021 block: '기타변동' −20 → '소유주와의 거래 합계' and
    # '자본 증가(감소) 합계' both printed 20 without parentheses; both must become −20.
    from fin2.extract.sce_sign_repair import _Cell as C, _proven_subtotals, _subtotal_fixes
    rows = (("2021.01.01 (기초자본)", 1000), ("기타변동", -20), ("소유주와의 거래 합계", 20),
            ("자본 증가(감소) 합계", 20), ("2021.12.31 (기말자본)", 980))
    cells = [C(line=None, basis="separate", label_raw=l, col_label="자본>주식발행초과금", value=v)
             for l, v in rows]
    subs = _proven_subtotals(cells, [1, 2, 3])
    assert subs == [2, 3]
    assert sorted(_subtotal_fixes(cells, [1, 2, 3], subs, {})) == [(2, -1), (3, -1)]


def _unclosed_block_filing(bs_total=880):
    """화승엔터프라이즈 `20210319000901` shape: the opening 기타자본구성요소 lost its parentheses
    (BS at the prior year end: −140) and the column has another defect (a movement that does
    not belong), so the block cannot close either way."""
    return [
        *_sce_row("2018.01.01 (기초자본)", 0, 140, 1000, 880),
        *_sce_row("무상증자", 1, -500, None, -500),
        *_sce_row("2018.12.31 (기말자본)", 2, -90, 1000, 910),
    ], {datetime.date(2017, 12, 31): [("separate", "기타자본구성요소", -140), ("separate", "자본총계", bs_total)]}


def test_r190d_dated_bs_balance_sign_applies_without_a_closing_block():
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines, prior = _unclosed_block_filing()
    fixes = apply_dated_balance_signs(lines, prior)
    got = {ln.row_order: ln.value_won for ln in lines if ln.col_index == 0}
    assert got == {0: -140, 1: -500, 2: -90}
    assert [(c.row_order, c.new_value) for c in fixes] == [(0, -140)]


def test_r190d_needs_the_equity_totals_to_agree():
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines, prior = _unclosed_block_filing(bs_total=999)
    assert apply_dated_balance_signs(lines, prior) == []


def test_r190d_leaves_movement_rows_alone():
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines, prior = _unclosed_block_filing()
    # A movement row with the same magnitude as the anchored balance is not a balance row.
    lines += _sce_row("기타변동", 5, 140, None, 140)
    apply_dated_balance_signs(lines, prior)
    assert next(ln.value_won for ln in lines if ln.row_order == 5 and ln.col_index == 0) == 140


def test_r190d_does_not_override_a_cell_proven_twice_inside_the_sce():
    # 인지컨트롤스 `20180515001307` shape: the closing OCI is printed with parentheses, its
    # block closes and its row identity holds; the (wrong) BS value has the other sign.
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines = [
        *_sce_row("2017.01.01 (기초자본)", 0, -100, 1000, 900),
        *_sce_row("해외사업환산손익", 1, -20, None, -20),
        *_sce_row("2017.12.31 (기말자본)", 2, -120, 1000, 880),
    ]
    prior = {datetime.date(2017, 12, 31): [("separate", "기타자본구성요소", 120), ("separate", "자본총계", 880)]}
    assert apply_dated_balance_signs(lines, prior) == []
