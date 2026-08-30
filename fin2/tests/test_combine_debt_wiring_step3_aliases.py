"""B1-D2 step3 "나머지 소수 라벨" (2026-08-31, docs/plans/valuation_daily_blockers_da_
netdebt_design_2026-08-30.md §2-7 순서3) — 신주인수권부사채(BW)/교환사채(EB), each
split into its own current/noncurrent canonical pair (bs.warrant_bond/
bs.current_warrant_bond, bs.exchange_bond/bs.current_exchange_bond) for the same
double-count reason as step2's convertible_bond split (measured co-occurrence with
사채/전환사채/each other: 30-434 filings per pair).

Also covers a batch of fuzzy-collision regressions discovered while auditing step2/3's
new exact aliases against the full debt/bond label universe: several genuinely-noncurrent
or genuinely-current labels were fuzzy-landing on the WRONG bucket (still net_debt-total
-safe on their own, since all these canonicals feed the same _V3_ST_DEBT_PARTS/
_V3_LT_DEBT_PARTS sum) but some had a measured real conflict risk (co-occurring with the
wrong bucket's OWN exact alias in the same filing, which would HELD/lose BOTH amounts).
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


def test_exchange_bond_labels_map_to_new_canonicals():
    m = get_mapper()
    assert m.map("교환사채", fs_section="bs").account_code == "bs.exchange_bond"
    assert m.map("비유동교환사채", fs_section="bs").account_code == "bs.exchange_bond"
    for label in ("유동성교환사채", "교환사채(유동)", "유동교환사채"):
        r = m.map(label, fs_section="bs")
        assert r.account_code == "bs.current_exchange_bond", (label, r.account_code)
        assert r.stage == "exact"


def test_warrant_bond_labels_map_to_new_canonicals():
    m = get_mapper()
    assert m.map("신주인수권부사채", fs_section="bs").account_code == "bs.warrant_bond"
    assert m.map("비유동신주인수권부사채", fs_section="bs").account_code == "bs.warrant_bond"
    for label in ("유동성신주인수권부사채", "신주인수권부사채(유동)", "유동신주인수권부사채"):
        r = m.map(label, fs_section="bs")
        assert r.account_code == "bs.current_warrant_bond", (label, r.account_code)
        assert r.stage == "exact"


def test_four_instrument_families_coexist_without_conflict():
    # 434 filings measured (2026-08-31) have both a 전환사채 row and a 신주인수권부사채
    # row -- each of the 4 bond-family instruments (사채/전환사채/교환사채/신주인수권부사채)
    # must resolve independently even when all present together.
    cands = {
        "bs.bond": [_row(10, "exact", "사채", "부채>비유동부채")],
        "bs.convertible_bond": [_row(20, "exact", "전환사채", "부채>비유동부채")],
        "bs.exchange_bond": [_row(30, "exact", "교환사채", "부채>비유동부채")],
        "bs.warrant_bond": [_row(40, "exact", "신주인수권부사채", "부채>비유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.bond"] == 10
    assert confirmed["bs.convertible_bond"] == 20
    assert confirmed["bs.exchange_bond"] == 30
    assert confirmed["bs.warrant_bond"] == 40
    assert not conflicts


def test_additive_debt_includes_exchange_and_warrant_bond_parts():
    canon = {
        "bs.short_term_debt": 100,
        "bs.current_exchange_bond": 5,
        "bs.current_warrant_bond": 7,
        "bs.long_term_debt": 200,
        "bs.exchange_bond": 11,
        "bs.warrant_bond": 13,
    }
    st, lt = _additive_debt_for_net_debt(canon, col={})
    assert st == 112
    assert lt == 224


# ── fuzzy-collision regressions discovered during step2/3's alias audit ────────────
# Each of these was previously landing on a semantically wrong AND (in the cited count)
# measurably conflict-prone canonical before the corresponding exact alias was added.

def test_biyudong_noncurrent_remainder_not_confused_with_current_transfer():
    # '...의 비유동성 부분' (noncurrent remainder, 187+14 measured) must NOT fuzzy-collide
    # with '...의 유동성대체부분' (current-reclassified portion, step2's own alias) -- they
    # are opposite concepts.
    m = get_mapper()
    assert m.map("비유동차입금(사채포함)의비유동성부분", fs_section="bs").account_code == "bs.long_term_debt"
    assert m.map("비유동차입금의비유동성부분", fs_section="bs").account_code == "bs.long_term_debt"
    # and the '(사채포함)'-less current-transfer sibling (512 measured, much more common
    # than the '(사채포함)' form) must still resolve to the CURRENT bucket, not get pulled
    # toward the just-added long_term_debt alias by text-similarity noise.
    assert m.map("비유동차입금의유동성대체부분", fs_section="bs").account_code == "bs.current_portion_lt_debt"


def test_plain_bond_current_noncurrent_variants_not_confused_with_convertible():
    m = get_mapper()
    assert m.map("유동사채", fs_section="bs").account_code == "bs.current_bond"
    assert m.map("비유동성사채", fs_section="bs").account_code == "bs.bond"
    assert m.map("사채(비유동)", fs_section="bs").account_code == "bs.bond"


def test_plain_bond_variants_do_not_conflict_with_their_own_family():
    # Real-filing risk (measured 2026-08-31): '유동사채' co-occurs with a plain 사채/장기
    # 사채/회사채 row in 43 filings -- if '유동사채' aliased to bs.bond (its pre-fix fuzzy
    # target), _resolve() would see two differing candidates and HELD the whole canonical.
    cands = {
        "bs.bond": [_row(100, "exact", "사채", "부채>비유동부채")],
        "bs.current_bond": [_row(5, "exact", "유동사채", "부채>유동부채")],
    }
    confirmed, conflicts = _resolve(cands)
    assert confirmed["bs.bond"] == 100
    assert confirmed["bs.current_bond"] == 5
    assert not conflicts
