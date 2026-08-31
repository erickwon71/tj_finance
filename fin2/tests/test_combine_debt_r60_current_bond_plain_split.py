"""R60 (2026-08-31, docs/plans/bs_current_portion_lt_debt_concept_split_design_
2026-08-31.md) — '유동성사채'(사채의 유동성 대체분) split out of
bs.current_portion_lt_debt into its own leaf canonical bs.current_bond_plain.

Before this split, '유동성사채' shared bs.current_portion_lt_debt with '유동성장기
부채'/'유동성장기차입금' (a different concept: 장기부채/차입금의 유동성 대체분).
Measured (2026-08-31): 3,405 filings/487 corps co-occur both as separate BS rows,
all HELD (canonical-wide, both amounts lost) since _resolve() saw two differing
candidates for the same canonical. Folding '유동성사채' into the existing
bs.current_bond instead (whose own aliases look similar) was rejected: 227 filings
co-occur with bs.current_bond's aliases and 176 of those have genuinely different
values -- would trade one HELD population for another.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper
from fin2.layer3.combine import _resolve, _additive_debt_for_net_debt


def _row(value, stage, label_raw, section_path):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "table_seq": 0}


def test_current_bond_plain_label_maps_to_new_canonical():
    m = get_mapper()
    r = m.map("유동성사채", fs_section="bs")
    assert r.account_code == "bs.current_bond_plain"
    assert r.stage == "exact"


def test_current_portion_lt_debt_labels_unaffected():
    m = get_mapper()
    for label in ("유동성장기부채", "유동성장기차입금",
                  "비유동차입금(사채포함)의유동성대체부분", "비유동차입금의유동성대체부분"):
        assert m.map(label, fs_section="bs").account_code == "bs.current_portion_lt_debt"


def test_bond_and_lt_debt_current_portions_coexist_without_conflict():
    # Real reproduction (00102858 FY2008 consolidated): '유동성사채' 75,056,000,000
    # and '유동성장기부채' 53,884,912,604 as separate BS rows in the same filing.
    # Before the split both landed on bs.current_portion_lt_debt -> HELD (both lost).
    cands = {
        "bs.current_bond_plain": [_row(75_056_000_000, "exact", "유동성사채", "부채>유동부채")],
        "bs.current_portion_lt_debt": [_row(53_884_912_604, "exact", "유동성장기부채", "부채>유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.current_bond_plain"] == 75_056_000_000
    assert confirmed["bs.current_portion_lt_debt"] == 53_884_912_604
    assert not conflicts


def test_current_bond_plain_does_not_conflict_with_current_bond_family():
    # The rejected merge-into-bs.current_bond alternative: 176/227 measured
    # co-occurrences with bs.current_bond's own aliases have DIFFERENT values, which
    # would have HELD both. Kept as separate canonicals, each resolves independently
    # even when both present in the same filing.
    cands = {
        "bs.current_bond_plain": [_row(10, "exact", "유동성사채", "부채>유동부채")],
        "bs.current_bond": [_row(20, "exact", "유동사채", "부채>유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.current_bond_plain"] == 10
    assert confirmed["bs.current_bond"] == 20
    assert not conflicts


def test_additive_debt_includes_current_bond_plain_part():
    canon = {
        "bs.short_term_debt": 100,
        "bs.current_portion_lt_debt": 50,
        "bs.current_bond_plain": 30,
        "bs.long_term_debt": 200,
    }
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 180
    assert lt == 200
