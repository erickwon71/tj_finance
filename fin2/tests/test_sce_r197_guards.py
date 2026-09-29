"""R197 — two SCE sign-repair guards found while investigating the R192/R193 defect candidates.

a) (dropped after measurement, see the test below); b) R162-e may not break a holding row identity
   whose total column already closes as printed (케일럼 `20250515000242`), except for rows negative by
   nature (dividends, treasury-stock purchases); c) exemption list for two filings with source defects.
`docs/qa/r192_r193_defect_candidates_2026-09-29.md`, `docs/PARSING_RULES.md` R197.
"""
from __future__ import annotations

import datetime

import pytest

import fin2.extract.sce_sign_repair as ssr
from fin2.extract.sce_sign_repair import repair_sce_sign_loss
from fin2.tests.test_sce_mirror_guard_r190 import _Line, _TOT, _dms_2013_block


@pytest.fixture(autouse=True)
def _restore_switches():
    saved = ssr._R162E_ROW_GUARD
    yield
    ssr._R162E_ROW_GUARD = saved


def _conflicting_is_block():
    """DMS block, but the earlier report's IS prints the movement as a loss: the BS-anchored solution
    and the IS anchor cannot both hold. (R197-a would have re-solved without the IS anchor; measured
    on 107,951 filings it contradicted the IS of the same item on 24 of 48 cells, so it was dropped.)"""
    lines, prior_bal, _ = _dms_2013_block()
    prior_is = {(datetime.date(2013, 1, 1), datetime.date(2013, 12, 31)):
                [("separate", "VIII. 기타포괄손익", -413584791)]}
    return lines, prior_bal, prior_is


def test_r197a_dropped_conflicting_is_anchor_leaves_the_block_as_printed():
    lines, prior_bal, prior_is = _conflicting_is_block()
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [420359510, 413584791, 6774719]


def test_r197a_agreeing_is_anchor_is_unchanged():
    lines, prior_bal, prior_is = _dms_2013_block()
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [-420359510, 413584791, -6774719]


_RE, _TOTAL = "자본>이익잉여금", "자본>자본 합계"


def _calum_like(total_closes_as_printed=True):
    """The retained-earnings column only closes if the profit row is flipped (its balances contradict
    the total column); the total column closes as printed."""
    rows = (("2024.01.01 (기초자본)", 1000, 1000), ("당기순이익(손실)", 100, 100),
            ("2024.03.31 (기말자본)", 900, 1100 if total_closes_as_printed else 1234))
    lines = []
    for i, (label, re_v, tot) in enumerate(rows):
        lines.append(_Line("SCE", "separate", label, re_v, col_index=0, col_label=_RE, row_order=i, period="Q1"))
        lines.append(_Line("SCE", "separate", label, tot, col_index=1, col_label=_TOTAL, row_order=i, period="Q1"))
    return lines


def _profit(lines):
    return next(ln for ln in lines if ln.row_order == 1 and ln.col_index == 0)


def test_r197b_r162e_flip_is_refused_when_the_partner_column_closes_as_printed():
    ssr._R162E_ROW_GUARD = True
    lines = _calum_like()
    repair_sce_sign_loss(lines, {})
    assert _profit(lines).value_won == 100
    assert next(ln for ln in lines if ln.row_order == 1 and ln.col_index == 1).value_won == 100


def test_r197b_without_the_guard_the_flip_happens():
    ssr._R162E_ROW_GUARD = False
    lines = _calum_like()
    repair_sce_sign_loss(lines, {})
    assert _profit(lines).value_won == -100                     # the defect


def test_r197b_partner_column_that_does_not_close_does_not_block_the_flip():
    ssr._R162E_ROW_GUARD = True
    lines = _calum_like(total_closes_as_printed=False)
    repair_sce_sign_loss(lines, {})
    assert _profit(lines).value_won == -100


def _with_rcept(lines, rcept):
    for ln in lines:
        ln.rcept_no = rcept
    return lines


def test_r197c_exempt_filing_ignores_the_prior_is_anchors():
    """A filing listed in `_PRIOR_IS_ANCHOR_EXEMPT` is solved as if no earlier IS existed (R192 off).
    Contrast on a block whose IS anchor conflicts with the BS anchors (fallback switched off)."""
    lines, prior_bal, prior_is = _conflicting_is_block()
    _with_rcept(lines, "20150515001151")
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [-420359510, 413584791, -6774719]


def test_r197c_other_filing_keeps_the_prior_is_anchors():
    lines, prior_bal, prior_is = _conflicting_is_block()
    _with_rcept(lines, "20990101000001")
    repair_sce_sign_loss(lines, prior_bal, prior_is)
    assert [ln.value_won for ln in lines[:3]] == [420359510, 413584791, 6774719]      # unsolved as printed


def test_r197c_listed_filings_carry_their_evidence():
    assert set(ssr._PRIOR_IS_ANCHOR_EXEMPT) == {"20150515001151", "20191114000854"}
    assert all(ssr._PRIOR_IS_ANCHOR_EXEMPT.values())


def test_r197b_dividend_row_is_still_flipped_by_r162e():
    """Dividends are negative by nature: the R162-e flip is right even when the total column closes as printed."""
    ssr._R162E_ROW_GUARD = True
    lines = _calum_like()
    for ln in lines:
        if ln.row_order == 1:
            ln.label_raw = "배당금지급"
    repair_sce_sign_loss(lines, {})
    assert _profit(lines).value_won == -100


def test_r197b_treasury_stock_purchase_row_is_still_flipped_by_r162e():
    ssr._R162E_ROW_GUARD = True
    lines = _calum_like()
    for ln in lines:
        if ln.row_order == 1:
            ln.label_raw = "Ⅴ.자기주식의 처분(취득)"
    repair_sce_sign_loss(lines, {})
    assert _profit(lines).value_won == -100
