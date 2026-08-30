"""B1-D1 (2026-08-30, docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md
§2-4) — _CURRENT_STRICT drops are rerouted to their non-current sibling canonical
(_NONCURRENT_SIBLING) instead of being discarded, with the guards that prevent
double-counting.

Reproduction case: 00130763 FY2024 consolidated — '차입금' under
section_path='부채>비유동부채' exact-matches bs.short_term_debt, gets dropped by
_CURRENT_STRICT, and used to vanish entirely instead of reaching bs.long_term_debt
(net_debt short by exactly that amount).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve  # noqa: E402


def _row(value, stage, label_raw, section_path):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "table_seq": 0}


def test_section_only_noncurrent_row_reroutes_to_long_term_debt():
    # 00130763 FY2024 cons reproduction: '단기차입금' current + '차입금' dropped by
    # _CURRENT_STRICT because section_path says 비유동, but the label text alone
    # doesn't say so. It must now land in bs.long_term_debt instead of vanishing.
    cands = {
        "bs.short_term_debt": [
            _row(113_802_813_293, "exact", "단기차입금", "부채>유동부채"),
            _row(101_825_482_368, "exact", "차입금", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 113_802_813_293
    assert confirmed["bs.long_term_debt"] == 101_825_482_368


def test_guard1_sibling_already_has_candidates_not_overwritten():
    # Company disclosed 장기차입금 as its own line already -> the section-only-noncurrent
    # row under bs.short_term_debt must NOT be added on top (would double-count).
    cands = {
        "bs.short_term_debt": [
            _row(100, "exact", "단기차입금", "부채>유동부채"),
            _row(999, "exact", "차입금", "부채>비유동부채"),
        ],
        "bs.long_term_debt": [
            _row(500, "exact", "장기차입금", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 100
    assert confirmed["bs.long_term_debt"] == 500  # unchanged, not 500+999


def test_guard2_label_already_says_noncurrent_not_rerouted():
    # If the label itself says 장기/비유동, it's not the section-only class this reroute
    # targets -- something else is going on, so it's left to the existing drop-only
    # behavior (no bs.long_term_debt entry created from it).
    cands = {
        "bs.short_term_debt": [
            _row(100, "exact", "단기차입금", "부채>유동부채"),
            _row(999, "exact", "장기차입금(오분류)", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 100
    assert "bs.long_term_debt" not in confirmed


def test_guard3_all_candidates_noncurrent_not_rerouted():
    # Every candidate for bs.short_term_debt is non-current (by section only) -> the
    # existing _CURRENT_STRICT filter leaves them untouched (no-MISSING safety net), so
    # the row still gets confirmed as short_term_debt itself. Rerouting a copy to
    # long_term_debt here would double the amount, not recover it -- must not happen.
    cands = {
        "bs.short_term_debt": [
            _row(777, "exact", "차입금", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 777
    assert "bs.long_term_debt" not in confirmed


def test_current_only_candidates_unaffected():
    # Normal case, no non-current rows at all -> unchanged behavior.
    cands = {
        "bs.short_term_debt": [
            _row(100, "exact", "단기차입금", "부채>유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 100
    assert "bs.long_term_debt" not in confirmed
