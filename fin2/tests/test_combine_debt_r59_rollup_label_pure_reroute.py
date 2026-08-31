"""R59 (2026-08-31, docs/plans/r59_rollup_debt_label_held_bug_design_2026-08-31.md) —
bs.long_term_debt's rollup ('사채+차입금' combined, maturity-blind) alias family
(e.g. '장기차입금및사채'/'사채및장기차입금'/'차입금및사채') HELD-loses the WHOLE canonical
when the same combined label appears as a separate line under both 유동부채 and
비유동부채 sections in one filing.

Unlike the existing _CURRENT_CONTAMINATED_NONCURRENT_SIBLING bond-family fix (R58, step3
fixup), the reroute classifier here (_is_current_by_section_only_pure) does NOT veto on
label_raw containing 장기/비유동 — bs.long_term_debt's own combined alias text routinely
contains '장기' (measured 2026-08-31: 417 current-side instances, only 1 (0.2%) contains
장기/비유동 in label_raw — and that 1 is the real-world repro below), so a label-based
veto would refuse to reroute exactly the contaminating instance.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.account_mapper import get_mapper
from fin2.layer3.combine import _resolve


def _row(value, stage, label_raw, section_path):
    return {"value": value, "stage": stage, "label_raw": label_raw,
            "section_path": section_path, "table_seq": 0}


def test_reversed_word_order_rollup_label_now_maps_to_long_term_debt():
    # Side-finding while re-auditing this fix (2026-08-31): '차입금및사채' (차입금 first)
    # already fuzzy-mapped to bs.long_term_debt, but the reversed word order '사채및차입금'
    # (사채 first) scored below the fuzzy threshold and fell to 'unknown' -- so those rows
    # never even entered bs.long_term_debt's candidate pool, meaning the R59 reroute above
    # could not help them at all. Measured 42 affected filings (00121507/00181712 FY2011-14/
    # 00877059 etc.), v2 fails identically (pre-existing gap, not a regression). Fixed by
    # registering '사채및차입금' as an exact alias (account_maps/bs_accounts.py).
    m = get_mapper()
    r = m.map("사채및차입금", fs_section="bs")
    assert r.account_code == "bs.long_term_debt"
    assert r.stage == "exact"
    # normalize_account_name() collapses spaces between Korean characters (including
    # around '및'), so the spaced variant is covered by the same exact alias via the
    # 'normalized' stage without needing its own registration.
    r2 = m.map("사채 및 차입금", fs_section="bs")
    assert r2.account_code == "bs.long_term_debt"


def test_rollup_label_reroutes_even_when_label_text_contains_jangi():
    # Real reproduction (00181712 FY2024 cons): '사채 및 장기차입금' (current, label
    # text itself contains '장기') co-exists with '사채및장기차입금' (noncurrent, same
    # normalized concept). Before the fix both mapped to bs.long_term_debt -> held ->
    # the full 62,861,073,000,000 vanished from net_debt. The label-based veto used by
    # the bond-family fixup would wrongly refuse this case (label_raw contains '장기') —
    # the pure section-only classifier must reroute it anyway.
    cands = {
        "bs.long_term_debt": [
            _row(14_788_886_000_000, "fuzzy", "사채 및 장기차입금", "부채>유동부채"),
            _row(48_073_129_000_000, "fuzzy", "사채및장기차입금", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.long_term_debt"] == 48_073_129_000_000
    assert confirmed["bs.short_term_debt"] == 14_788_886_000_000
    assert not conflicts


def test_rollup_label_reroutes_for_the_more_common_jangi_free_variant():
    # More common variant (measured majority, no '장기'/'비유동' in either instance's
    # label): '차입금및사채' under both sections in the same filing.
    cands = {
        "bs.long_term_debt": [
            _row(100, "fuzzy", "차입금및사채", "부채>유동부채"),
            _row(300, "fuzzy", "차입금및사채", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.long_term_debt"] == 300
    assert confirmed["bs.short_term_debt"] == 100
    assert not conflicts


def test_all_candidates_current_by_section_left_untouched():
    # Only an ambiguous current-by-section candidate, no genuine noncurrent sibling to
    # protect -- left as bs.long_term_debt's own confirmed value (no MISSING period),
    # not rerouted.
    cands = {
        "bs.long_term_debt": [_row(999, "fuzzy", "차입금및사채", "부채>유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.long_term_debt"] == 999
    assert "bs.short_term_debt" not in confirmed
    assert not conflicts


def test_current_sibling_already_populated_not_overwritten():
    # guard: if bs.short_term_debt already has its own genuine candidate (e.g. a
    # separately-disclosed '단기차입금'), the rerouted current-by-section rollup row
    # must NOT be added on top (would double-count).
    cands = {
        "bs.long_term_debt": [
            _row(100, "fuzzy", "차입금및사채", "부채>유동부채"),
            _row(300, "fuzzy", "차입금및사채", "부채>비유동부채"),
        ],
        "bs.short_term_debt": [
            _row(50, "exact", "단기차입금", "부채>유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.short_term_debt"] == 50  # unchanged, not 50+100
    # bs.long_term_debt still holds two differing candidates (100 vs 300) since the
    # guard skipped the reroute -- left unconfirmed, an unresolved pre-existing conflict,
    # not a regression: the fixup only ever REMOVES a conflict source, never manufactures
    # one, and critically the ambiguous 100 is not silently summed into either side.
    assert confirmed.get("bs.long_term_debt") is None


def test_does_not_interfere_with_bond_family_pure_reroute_in_same_call():
    # Sanity: the new PURE dict/loop and the existing label-vetoed
    # _CURRENT_CONTAMINATED_NONCURRENT_SIBLING loop fire independently in the same
    # _resolve() call without cross-contaminating each other's canonicals.
    cands = {
        "bs.long_term_debt": [
            _row(100, "fuzzy", "차입금및사채", "부채>유동부채"),
            _row(300, "fuzzy", "차입금및사채", "부채>비유동부채"),
        ],
        "bs.convertible_bond": [
            _row(20, "exact", "전환사채", "부채>유동부채"),
            _row(40, "exact", "비유동전환사채", "부채>비유동부채"),
        ],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.long_term_debt"] == 300
    assert confirmed["bs.short_term_debt"] == 100
    assert confirmed["bs.convertible_bond"] == 40
    assert confirmed["bs.current_convertible_bond"] == 20
    assert not conflicts
