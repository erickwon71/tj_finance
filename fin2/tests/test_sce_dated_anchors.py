"""R187 dated SCE balance anchors and R188 balance tolerance.

`docs/PARSING_RULES.md` R187/R188, `docs/plans/sce_opening_prior_period_anchor_design_2026-09-27.md`.
"""
from __future__ import annotations

import datetime

from fin2.extract.sce_dated_anchors import add_dated_anchors, balance_anchor_date
from fin2.extract.sce_sign_repair import (
    _Cell, _required_sign, build_sign_anchors, repair_sce_balance_tolerance,
)


class _Line:
    def __init__(self, statement, basis, label_raw, value_won, *, col_index=0,
                 col_label=None, row_order=0, table_seq=0, period="Q1"):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.col_label = col_label
        self.row_order = row_order
        self.table_seq = table_seq
        self.report_fiscal_period = period


_ADJ, _TOT = "자본>자본조정", "자본>자본 합계"


def _q1_filing(bs_prior_total=960):
    """2014 Q1: SCE current block 2014.01.01 → 2014.03.31. BS col 0 = 2014.03.31,
    col 1 = 2013.12.31. 자본조정 opening 40 lost its parentheses."""
    return [
        _Line("SCE", "separate", "2014.01.01 (기초자본)", 40, col_index=0, col_label=_ADJ, row_order=0),
        _Line("SCE", "separate", "2014.01.01 (기초자본)", 960, col_index=1, col_label=_TOT, row_order=0),
        _Line("SCE", "separate", "2014.03.31 (기말자본)", -50, col_index=0, col_label=_ADJ, row_order=1),
        _Line("SCE", "separate", "2014.03.31 (기말자본)", 950, col_index=1, col_label=_TOT, row_order=1),
        _Line("BS", "separate", "자본조정", -50, col_index=0),
        _Line("BS", "separate", "자본총계", 950, col_index=0),
        _Line("BS", "separate", "자본조정", -40, col_index=1),
        _Line("BS", "separate", "자본총계", bs_prior_total, col_index=1),
    ]


def _opening_cell(lines):
    ln = lines[0]
    return _Cell(line=ln, basis=ln.basis, label_raw=ln.label_raw, col_label=ln.col_label,
                 value=ln.value_won)


def test_balance_anchor_date_opening_is_the_day_before():
    assert balance_anchor_date("2014.01.01 (기초자본)") == datetime.date(2013, 12, 31)
    assert balance_anchor_date("2014.03.31 (기말자본)") == datetime.date(2014, 3, 31)
    assert balance_anchor_date("당기순이익") is None


def test_stage1_bs_prior_column_proves_the_opening_sign():
    lines = _q1_filing()
    anchors = add_dated_anchors(build_sign_anchors(lines), lines)
    sign, label = _required_sign(_opening_cell(lines), anchors)
    assert sign == -1 and label == "자본조정@2013-12-31"


def test_stage1_needs_the_equity_totals_to_agree():
    # The BS prior-year total differs from the SCE opening total (restated) → no evidence.
    lines = _q1_filing(bs_prior_total=999)
    anchors = add_dated_anchors(build_sign_anchors(lines), lines)
    sign, _ = _required_sign(_opening_cell(lines), anchors)
    assert sign is None


def test_stage2_prior_annual_balances_prove_the_opening_sign():
    lines = [ln for ln in _q1_filing() if not (ln.statement == "BS" and ln.col_index == 1)]
    prior = {datetime.date(2013, 12, 31): [("separate", "자본조정", -40), ("separate", "자본총계", 960)]}
    anchors = add_dated_anchors(build_sign_anchors(lines), lines, prior)
    sign, _ = _required_sign(_opening_cell(lines), anchors)
    assert sign == -1
    # Without the prior report there is no evidence for this magnitude.
    anchors = add_dated_anchors(build_sign_anchors(lines), lines)
    assert _required_sign(_opening_cell(lines), anchors)[0] is None


# ── R188: two identities close within 1,000 won only after the flip ──────────
def _wonik_table(oci_open=705_022_515, oci_close=7_250_704_579):
    """원익큐브 20160330000801 별도 2013 block, reduced to OCI + total (+ one other part)."""
    oci, oth, tot = "자본>기타포괄손익누계액", "자본>기타", "자본>자본 합계"
    return [
        _Line("SCE", "separate", "2013.01.01 (기초자본)", oci_open, col_index=0, col_label=oci, row_order=0, period="FY"),
        _Line("SCE", "separate", "2013.01.01 (기초자본)", 53_428_908_054, col_index=1, col_label=oth, row_order=0, period="FY"),
        _Line("SCE", "separate", "2013.01.01 (기초자본)", 52_723_885_541, col_index=2, col_label=tot, row_order=0, period="FY"),
        _Line("SCE", "separate", "보험수리적손익", 173_881_561, col_index=0, col_label=oci, row_order=1, period="FY"),
        _Line("SCE", "separate", "매도가능금융자산평가", 7_781_845_531, col_index=0, col_label=oci, row_order=2, period="FY"),
        _Line("SCE", "separate", "2013.12.31 (기말자본)", oci_close, col_index=0, col_label=oci, row_order=3, period="FY"),
    ]


def test_r188_flips_when_both_identities_close_within_tolerance():
    # parts: −705,022,515 + 53,428,908,054 = 52,723,885,539 vs total …541 (2 won);
    # roll-forward: −705,022,515 + 7,955,727,092 = 7,250,704,577 vs 7,250,704,579 (2 won).
    lines = _wonik_table()
    fixes = repair_sce_balance_tolerance(lines)
    assert lines[0].value_won == -705_022_515
    assert [f.anchor_label for f in fixes] == ["R188 허용오차 1000원 이중항등식"]


def test_r188_needs_both_identities():
    # The roll-forward still misses by far more than 1,000 won after the flip.
    lines = _wonik_table(oci_close=9_000_000_000)
    repair_sce_balance_tolerance(lines)
    assert lines[0].value_won == 705_022_515


def test_r188_positive_anchor_vetoes():
    lines = _wonik_table() + [
        _Line("BS", "separate", "기타포괄손익누계액", 705_022_515, col_index=0, period="FY")]
    repair_sce_balance_tolerance(lines)
    assert lines[0].value_won == 705_022_515


# ── R189: row identity closed by sibling cells that their own column supports ──
from fin2.extract.sce_sign_repair import repair_sce_sibling_cells  # noqa: E402


def _sibling_table(total_closing=85):
    """기타포괄 already fixed (−10); the total column still prints +10 for the same row
    and also lost the dividend's parentheses (+5): 100 + 5 + 10 ≠ 85."""
    oci, tot = "자본>기타포괄손익누계액", "자본>자본 합계"
    rows = [("2012.01.01 (기초자본)", {0: 40, 1: 100}), ("배당금지급", {1: 5}),
            ("해외사업환산차이", {0: -10, 1: 10}), ("2012.12.31 (기말자본)", {0: 30, 1: total_closing})]
    out = []
    for ro, (lab, cells) in enumerate(rows):
        for ci, v in cells.items():
            out.append(_Line("SCE", "consolidated", lab, v, col_index=ci,
                             col_label=oci if ci == 0 else tot, row_order=ro, period="FY"))
    return out


def test_r189_flips_the_total_cell_its_column_supports():
    # The IS prints the translation loss as (10): the sign is known from outside the table.
    lines = _sibling_table() + [_Line("IS", "consolidated", "해외사업환산손실", -10, period="FY")]
    fixes = repair_sce_sibling_cells(lines)
    assert [(f.label_raw, f.new_value) for f in fixes] == [("해외사업환산차이", -10)]


def test_r189_movement_without_outside_evidence_is_left_alone():
    # OCI/NI rows contradicted the IS in 60 of 145 evidenced cells, so no IS → no flip.
    assert repair_sce_sibling_cells(_sibling_table()) == []


def test_r189_needs_the_column_to_shrink():
    # The total column would move away from closing (+10 is right for that column).
    lines = _sibling_table(total_closing=115)
    assert repair_sce_sibling_cells(lines) == []


# ── R189-b: the earlier report's IS for exactly this block's period ────────────
_PERIOD = (datetime.date(2012, 1, 1), datetime.date(2012, 12, 31))


def test_r189b_prior_is_for_the_block_period_is_outside_evidence():
    prior_income = {_PERIOD: [("consolidated", "해외사업환산손실", -10)]}
    fixes = repair_sce_sibling_cells(_sibling_table(), prior_income=prior_income)
    assert [(f.label_raw, f.new_value) for f in fixes] == [("해외사업환산차이", -10)]


def test_r189b_other_period_or_other_item_is_no_evidence():
    other_period = {(datetime.date(2011, 1, 1), datetime.date(2011, 12, 31)):
                    [("consolidated", "해외사업환산손실", -10)]}
    assert repair_sce_sibling_cells(_sibling_table(), prior_income=other_period) == []
    other_item = {_PERIOD: [("consolidated", "해외사업장순투자의 위험회피", -10)]}
    assert repair_sce_sibling_cells(_sibling_table(), prior_income=other_item) == []


def test_r189b_prior_is_positive_vetoes():
    prior_income = {_PERIOD: [("consolidated", "해외사업환산이익", 10)]}
    lines = _sibling_table() + [_Line("IS", "consolidated", "해외사업환산손실", -10, period="FY")]
    assert repair_sce_sibling_cells(lines, prior_income=prior_income) == []
