"""B1-D2 step1 "wiring" (2026-08-31, docs/plans/valuation_daily_blockers_da_netdebt_
design_2026-08-30.md §2-7) — net_debt-only additive debt sum that recovers the 3
already-registered but previously unread orphan canonicals (bs.current_portion_lt_debt/
bs.current_bond/bs.bond).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _additive_debt_for_net_debt  # noqa: E402


def test_orphan_canonicals_are_summed_into_short_and_long_debt():
    # 00126380-shaped case: 단기차입금 alone in short_term_debt, plus previously-dropped
    # 유동성장기부채/유동성회사채/사채 orphans that must now feed net_debt.
    canon = {
        "bs.short_term_debt": 100,
        "bs.current_portion_lt_debt": 50,
        "bs.current_bond": 10,
        "bs.long_term_debt": 200,
        "bs.bond": 30,
    }
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 160
    assert lt == 230


def test_no_orphans_present_falls_back_to_direct_map_value():
    canon = {"bs.short_term_debt": 100, "bs.long_term_debt": 200}
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 100
    assert lt == 200


def test_missing_side_stays_none():
    # Only short_term_debt present -> long side must stay None, not 0 (0 would silently
    # zero out net_debt's long_term_debt contribution instead of leaving it unconfirmed).
    canon = {"bs.short_term_debt": 100}
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 100
    assert lt is None


def test_double_count_guard_distrusts_sum_over_total_liabilities():
    # Mirrors rule_additive_debt's guard (fin2/standardize/rules.py:282): a company that
    # tags debt both as a rollup and as its details would double the sum past total
    # liabilities*1.05 -> distrust the additive sum entirely, both sides.
    canon = {
        "bs.short_term_debt": 900,
        "bs.current_portion_lt_debt": 900,
        "bs.long_term_debt": 100,
    }
    col = {"total_liabilities": 1000}  # 1900+100 = 2000 >> 1050
    st, lt = _additive_debt_for_net_debt(canon, col)
    assert st is None
    assert lt is None


def test_double_count_guard_not_tripped_when_within_bound():
    canon = {"bs.short_term_debt": 100, "bs.long_term_debt": 200}
    col = {"total_liabilities": 290}  # 300 <= 290*1.05=304.5 -> within bound, trusted
    st, lt = _additive_debt_for_net_debt(canon, col)
    assert st == 100
    assert lt == 200


def test_no_total_liabilities_never_gates():
    # total_liabilities missing/zero -> guard can't evaluate, so it must not block.
    canon = {"bs.short_term_debt": 100, "bs.current_portion_lt_debt": 50}
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 150
