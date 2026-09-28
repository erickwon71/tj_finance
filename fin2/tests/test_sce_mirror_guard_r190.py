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


def test_r190d_skips_deficit_columns():
    # 롤링스톤 `20190329004131`: the BS prints the deficit as a positive amount under '결손금'.
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines = [
        _Line("SCE", "separate", "2018.01.01 (기초자본)", -280, col_index=0, col_label="자본>결손금", row_order=0),
        _Line("SCE", "separate", "2018.01.01 (기초자본)", 720, col_index=1, col_label=_TOT, row_order=0),
        _Line("SCE", "separate", "당기순손실", -10, col_index=0, col_label="자본>결손금", row_order=1),
        _Line("SCE", "separate", "2018.12.31 (기말자본)", -300, col_index=0, col_label="자본>결손금", row_order=2),
    ]
    prior = {datetime.date(2017, 12, 31): [("separate", "결손금", 280), ("separate", "자본총계", 720)]}
    assert apply_dated_balance_signs(lines, prior) == []


def test_r190d_skips_when_both_sce_checks_get_worse():
    # 상아프론테크 `20260515001959` shape: flipping to the BS sign makes the column residual
    # and the row identity both worse → the BS value is the suspect one.
    from fin2.extract.sce_sign_repair import apply_dated_balance_signs
    lines = [
        *_sce_row("2025.01.01 (기초자본)", 0, -440, 1000, 560),
        *_sce_row("기타변동", 1, 30, None, 30),
        *_sce_row("2025.12.31 (기말자본)", 2, -400, 1000, 600),
    ]
    prior = {datetime.date(2024, 12, 31): [("separate", "기타자본구성요소", 440), ("separate", "자본총계", 560)]}
    assert apply_dated_balance_signs(lines, prior) == []


def test_r191_leading_subtotal_keeps_its_printed_sign():
    # BNK금융지주 `20260515002476` 연결 비지배지분: '총포괄손익' is printed above its components.
    # The run above it (신종자본증권배당 −5255) matches it by |value| only by coincidence;
    # the rows below (당기순이익 5255 … up to '총기타포괄손익') prove the printed +5255.
    from fin2.extract.sce_sign_repair import _Cell as C, _proven_subtotals, _subtotal_fixes
    rows = (("2025.01.01 (기초자본)", 448753), ("연차배당", 0), ("신종자본증권배당", -5255),
            ("총포괄손익", 5255), ("당기순이익(손실)", 5255), ("확정급여제도의재측정요소", 0),
            ("총기타포괄손익", 0), ("2025.03.31 (기말자본)", 448753))
    cells = [C(line=None, basis="consolidated", label_raw=l, col_label="자본>비지배지분", value=v)
             for l, v in rows]
    move_i = list(range(1, 7))
    subs = _proven_subtotals(cells, move_i)
    assert 3 in subs
    assert _subtotal_fixes(cells, move_i, subs, {}) == []


def test_r191_block_with_leading_subtotal_is_left_as_printed():
    nci = "자본>비지배지분"
    rows = (("2025.01.01 (기초자본)", 448753), ("신종자본증권배당", -5255), ("총포괄손익", 5255),
            ("당기순이익(손실)", 5255), ("총기타포괄손익", 0), ("2025.03.31 (기말자본)", 448753))
    lines = [_Line("SCE", "consolidated", l, v, col_index=0, col_label=nci, row_order=i)
             for i, (l, v) in enumerate(rows)]
    repair_sce_sign_loss(lines, {})
    assert [ln.value_won for ln in lines] == [v for _l, v in rows]


def _dms_2013_block():
    """DMS `20151113001218` 별도 기타자본구성요소 2013: the balances lost their parentheses
    (BS 2013-12-31 −6,774,719); the 2013 IS prints the OCI +413,584,791."""
    oth = "자본>기타자본구성요소"
    rows = (("2013.01.01 (기초자본)", 420359510), ("기타포괄손익", 413584791),
            ("2013.12.31 (기말자본)", 6774719))
    lines = [_Line("SCE", "separate", l, v, col_index=0, col_label=oth, row_order=i, period="FY")
             for i, (l, v) in enumerate(rows)]
    totals = (1000000000, 413584791, 1413584791)       # the dated anchor needs the BS 자본총계 (R187)
    lines += [_Line("SCE", "separate", l, t, col_index=1, col_label=_TOT, row_order=i, period="FY")
              for i, ((l, _v), t) in enumerate(zip(rows, totals))]
    prior_bal = {datetime.date(2013, 12, 31): [("separate", "기타자본구성요소", -6774719),
                                               ("separate", "자본총계", 1413584791)]}
    prior_is = {(datetime.date(2013, 1, 1), datetime.date(2013, 12, 31)):
                [("separate", "VIII. 기타포괄손익", 413584791)]}
    return lines, prior_bal, prior_is


def test_r192_prior_is_anchors_the_movement_so_the_opening_balance_flips():
    lines, prior_bal, prior_is = _dms_2013_block()
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [-420359510, 413584791, -6774719]


def test_r192_prior_is_alone_does_not_orient_a_block():
    # 태웅 `20150515001603` shape: no BS anchor, only an IS-backed movement → leave the block.
    lines, _, prior_is = _dms_2013_block()
    repair_sce_sign_loss(lines, {}, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [420359510, 413584791, 6774719]


def test_r192_ascii_roman_numeral_is_label_counts_as_a_subtotal():
    from fin2.extract.sce_sign_repair import _same_income_item
    assert _same_income_item("기타포괄손익", "VIII. 기타포괄손익")
    assert _same_income_item("기타포괄손익", "Ⅷ. 기타포괄손익")


def _oci_block(rows, prior_is_items):
    oci = "자본>기타포괄손익누계액"
    lines = [_Line("SCE", "consolidated", l, v, col_index=0, col_label=oci, row_order=i, period="FY")
             for i, (l, v) in enumerate(rows)]
    prior_is = {(datetime.date(2013, 1, 1), datetime.date(2013, 12, 31)):
                [("consolidated", lab, v) for lab, v in prior_is_items]}
    return lines, prior_is


def test_r192_no_anchor_on_an_unproven_trailing_subtotal():
    # 강남제비스코 `20150515001398` shape: '기타포괄손익 계' / '3.총포괄손익 계' are not recognised
    # as subtotals, so the block double-counts. An IS anchor on them must not let the
    # three components flip.
    rows = (("2013.01.01 (기초자본)", 2182), ("매도가능금융자산평가이익", 1251), ("외환차이", 63),
            ("기타포괄손익 계", 1314), ("3.총포괄손익 계", 1314), ("2013.12.31 (기말자본)", 3496))
    lines, prior_is = _oci_block(rows, [("(2)당기손익으로 재분류되는 항목", 1314)])
    repair_sce_sign_loss(lines, {}, prior_is)
    assert [ln.value_won for ln in lines] == [v for _l, v in rows]


def test_r192_no_anchor_on_a_leading_subtotal():
    # 코스모화학 `20181005000496` shape: '총포괄손익' and '기타포괄손익' printed above their components.
    rows = (("2013.01.01 (기초자본)", 150073), ("총포괄손익", 131), ("기타포괄손익", 131),
            ("매도가능금융자산평가이익", 166), ("부의지분법자본변동", -35), ("2013.12.31 (기말자본)", 150204))
    lines, prior_is = _oci_block(rows, [("XII.기타포괄이익", 131)])
    prior_bal = {datetime.date(2012, 12, 31): [("consolidated", "기타포괄손익누계액", 150073)],
                 datetime.date(2013, 12, 31): [("consolidated", "기타포괄손익누계액", 150204)]}
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines] == [v for _l, v in rows]
