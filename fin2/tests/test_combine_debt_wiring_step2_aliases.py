"""B1-D2 step2 "alias 3종" (2026-08-31, docs/plans/valuation_daily_blockers_da_netdebt_
design_2026-08-30.md §2-7 순서2) —
  1. '유동차입금(사채포함)' -> bs.short_term_debt
  2. '비유동차입금(사채포함)의유동성대체부분' -> bs.current_portion_lt_debt
  3. '전환사채' family -> new bs.convertible_bond / bs.current_convertible_bond,
     wired into _V3_LT_DEBT_PARTS / _V3_ST_DEBT_PARTS for net_debt.
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


def test_alias_1_maps_to_short_term_debt_exact():
    r = get_mapper().map("유동차입금(사채포함)", fs_section="bs")
    assert r.account_code == "bs.short_term_debt"
    assert r.stage == "exact"


def test_alias_2_maps_to_current_portion_lt_debt_exact():
    r = get_mapper().map("비유동차입금(사채포함)의유동성대체부분", fs_section="bs")
    assert r.account_code == "bs.current_portion_lt_debt"
    assert r.stage == "exact"


def test_convertible_bond_labels_map_to_new_canonicals():
    m = get_mapper()
    assert m.map("전환사채", fs_section="bs").account_code == "bs.convertible_bond"
    for label in ("전환사채(유동)", "유동전환사채", "유동성전환사채"):
        r = m.map(label, fs_section="bs")
        assert r.account_code == "bs.current_convertible_bond", (label, r.account_code)
        assert r.stage == "exact"


def test_bond_and_convertible_bond_coexist_without_conflict():
    # Real-filing shape (231 filings measured 2026-08-31): a company reports plain
    # '사채' AND '전환사채' as two separate BS lines in the same period. Before this
    # canonical existed, aliasing '전환사채' into bs.bond would have made _resolve()
    # see two conflicting candidates and HOLD bs.bond entirely (the whole amount lost,
    # not just the increment) -- they must resolve to two independent canonicals.
    cands = {
        "bs.bond": [_row(100, "exact", "사채", "부채>비유동부채")],
        "bs.convertible_bond": [_row(50, "exact", "전환사채", "부채>비유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.bond"] == 100
    assert confirmed["bs.convertible_bond"] == 50
    assert not conflicts


def test_current_portion_and_current_convertible_bond_coexist_without_conflict():
    # 1,300 filings measured (2026-08-31) have both a 유동성장기부채-family row and a
    # current-전환사채-family row in the same period -- same isolation requirement.
    cands = {
        "bs.current_portion_lt_debt": [_row(30, "exact", "유동성장기부채", "부채>유동부채")],
        "bs.current_convertible_bond": [_row(20, "exact", "유동성전환사채", "부채>유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.current_portion_lt_debt"] == 30
    assert confirmed["bs.current_convertible_bond"] == 20
    assert not conflicts


def test_additive_debt_includes_convertible_bond_parts():
    canon = {
        "bs.short_term_debt": 100,
        "bs.current_convertible_bond": 20,
        "bs.long_term_debt": 200,
        "bs.convertible_bond": 50,
    }
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 120
    assert lt == 250
