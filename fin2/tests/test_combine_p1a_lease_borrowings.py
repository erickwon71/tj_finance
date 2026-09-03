"""P1A(2026-09-03, docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md §Phase 1) —
lease_liability/borrowings_proceeds/borrowings_repaid v2 parity columns. Pure unit tests
for the two combine.py helper functions (no DB session needed), mirroring
test_combine_debt_wiring_net_debt.py's pattern for _additive_debt_for_net_debt.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import (  # noqa: E402
    _lease_liability_value, _borrowings_values,
    _lease_section_target, _route_bare_lease_by_section,
)


def test_lease_sums_current_and_noncurrent_parts():
    canon = {"bs.lease_current": 30, "bs.lease_noncurrent": 70}
    assert _lease_liability_value(canon) == 100


def test_lease_falls_back_to_bare_aggregate_when_no_parts():
    # v3-only case (v2 never had this): a filing reports a single un-split "리스부채"
    # total line instead of separate current/noncurrent rows.
    canon = {"bs.lease_liability": 150}
    assert _lease_liability_value(canon) == 150


def test_lease_prefers_parts_over_aggregate_when_both_present():
    canon = {"bs.lease_current": 30, "bs.lease_noncurrent": 70, "bs.lease_liability": 999}
    assert _lease_liability_value(canon) == 100


def test_lease_only_one_part_present_still_sums():
    canon = {"bs.lease_current": 30}
    assert _lease_liability_value(canon) == 30


def test_lease_absolute_value_applied():
    # BS stock amounts are never negative on the face of the statement, but guard against
    # a stray sign from upstream parsing the same way rule_additive_lease does (abs()).
    canon = {"bs.lease_current": -30, "bs.lease_noncurrent": 70}
    assert _lease_liability_value(canon) == 100


def test_lease_nothing_present_returns_none():
    assert _lease_liability_value({}) is None


def test_borrowings_sums_short_and_long_with_sign_preserved():
    canon = {
        "cf.borrow_proceeds_st": 50, "cf.borrow_proceeds_lt": 80,
        "cf.borrow_repaid_st": -20, "cf.borrow_repaid_lt": -40,
    }
    proceeds, repaid = _borrowings_values(canon)
    assert proceeds == 130
    assert repaid == -60


def test_borrowings_falls_back_to_bare_aggregate_independently_per_side():
    # proceeds side has parts, repaid side only has the bare aggregate (e.g. "차입금의상환")
    # — each side must fall back independently, not as an all-or-nothing pair.
    canon = {
        "cf.borrow_proceeds_st": 50, "cf.borrow_proceeds_lt": 80,
        "cf.borrowings_repaid": -60,
    }
    proceeds, repaid = _borrowings_values(canon)
    assert proceeds == 130
    assert repaid == -60


def test_borrowings_both_sides_fall_back_to_aggregate():
    canon = {"cf.borrowings_proceeds": 130, "cf.borrowings_repaid": -60}
    proceeds, repaid = _borrowings_values(canon)
    assert proceeds == 130
    assert repaid == -60


def test_borrowings_nothing_present_returns_none_none():
    assert _borrowings_values({}) == (None, None)


# ── section-based routing for bare "리스부채"/"금융리스부채" (found via source
# verification on 00101433/00101664 — see _route_bare_lease_by_section docstring) ──

def test_lease_section_target_noncurrent_by_section():
    assert _lease_section_target({"section_path": "부채>비유동부채"}) == "bs.lease_noncurrent"


def test_lease_section_target_current_by_section():
    assert _lease_section_target({"section_path": "부채>유동부채"}) == "bs.lease_current"


def test_lease_section_target_ambiguous_section_is_none():
    assert _lease_section_target({"section_path": "부채"}) is None
    assert _lease_section_target({"section_path": ""}) is None
    assert _lease_section_target({}) is None


def test_route_00101433_shape_current_bare_plus_noncurrent_own_label():
    # 경농 00101433 FY2025: bare "리스부채" sits under 부채>유동부채 (772,424,809) while
    # "비유동 리스부채" already resolved on its own to bs.lease_noncurrent (938,907,694).
    # The bare row must be routed to bs.lease_current (its own sibling has no candidates
    # yet), leaving bs.lease_noncurrent's own candidate untouched.
    cands = {
        "bs.lease_liability": [{"section_path": "부채>유동부채", "value_won": 772424809}],
        "bs.lease_noncurrent": [{"section_path": "부채>비유동부채", "value_won": 938907694}],
    }
    _route_bare_lease_by_section(cands)
    assert "bs.lease_liability" not in cands  # fully drained, nothing ambiguous left
    assert [r["value_won"] for r in cands["bs.lease_current"]] == [772424809]
    assert [r["value_won"] for r in cands["bs.lease_noncurrent"]] == [938907694]


def test_route_00101664_shape_same_bare_label_both_sections_resolved_separately():
    # 00101664: the exact same bare "리스부채" text appears twice in one filing, once
    # under 유동부채 and once under 비유동부채 with DIFFERENT values — without this
    # routing both would collide on bs.lease_liability and get HELD (conflict -> NULL).
    cands = {
        "bs.lease_liability": [
            {"section_path": "부채>유동부채", "value_won": 808557577},
            {"section_path": "부채>비유동부채", "value_won": 1201208120},
        ],
    }
    _route_bare_lease_by_section(cands)
    assert "bs.lease_liability" not in cands
    assert [r["value_won"] for r in cands["bs.lease_current"]] == [808557577]
    assert [r["value_won"] for r in cands["bs.lease_noncurrent"]] == [1201208120]


def test_route_genuine_aggregate_with_no_section_signal_stays_put():
    # A filing that reports a single un-split total with no 유동/비유동 subsection
    # nesting at all must stay in bs.lease_liability (the true aggregate case SPLIT_DRAFT
    # originally assumed for ALL bare labels — still valid for this narrower residual).
    cands = {"bs.lease_liability": [{"section_path": "부채", "value_won": 500}]}
    _route_bare_lease_by_section(cands)
    assert cands["bs.lease_liability"] == [{"section_path": "부채", "value_won": 500}]


def test_route_does_not_duplicate_when_sibling_already_has_its_own_candidate():
    # If bs.lease_current already has a genuine "유동리스부채"-labeled candidate, a
    # section-ambiguous... section-current bare row must NOT be added alongside it
    # (would double-count) -- it stays in the aggregate pool instead (conservative,
    # mirrors _NONCURRENT_SIBLING's guard 1).
    cands = {
        "bs.lease_liability": [{"section_path": "부채>유동부채", "value_won": 100}],
        "bs.lease_current": [{"section_path": "부채>유동부채", "value_won": 999}],
    }
    _route_bare_lease_by_section(cands)
    assert cands["bs.lease_current"] == [{"section_path": "부채>유동부채", "value_won": 999}]
    assert cands["bs.lease_liability"] == [{"section_path": "부채>유동부채", "value_won": 100}]


def test_route_no_lease_liability_key_is_a_noop():
    cands = {"bs.total_assets": [{"section_path": "자산", "value_won": 1}]}
    before = dict(cands)
    _route_bare_lease_by_section(cands)
    assert cands == before
