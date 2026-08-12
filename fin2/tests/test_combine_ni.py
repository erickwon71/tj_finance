"""
controlling_ni/noncontrolling_ni identity-trigger 확장 단위 테스트 (순수, DB 비의존).

docs/plans/std_v3_controlling_ni_oci_section_fix_design_2026-08-12.md §2/§4-2-1.
_resolve()가 is.controlling_ni/is.noncontrolling_ni 두 canonical에 한해 stage-rank
숏컷을 건너뛰고 항상 conflicts로 보내 _resolve_ni_attribution(identity 안전장치)이
반드시 판단 기회를 갖는지 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _resolve, _resolve_ni_attribution  # noqa: E402


def _row(value, stage="exact"):
    """Minimal candidate row shape (subset of _map_rows() output actually read by
    _resolve()/_resolve_ni_attribution())."""
    return {"value": value, "stage": stage, "label_raw": "지배기업의 소유주지분",
            "section_path": None, "table_seq": 0}


def test_split_resolves_via_identity_even_when_wrong_stage_outranks():
    # Wrong candidate(OCI-section value) is 'exact', correct one(NI-section value) is
    # only 'normalized' -- pre-fix, the stage-rank shortcut would have confirmed the
    # wrong value outright and never reached _resolve_ni_attribution (§1-A).
    cands = {
        "is.controlling_ni": [_row(100, "exact"), _row(90, "normalized")],
        "is.net_income": [_row(95)],
        "is.noncontrolling_ni": [_row(5)],
    }
    confirmed, conflicts = _resolve(cands)
    # Must be held (not confirmed by stage-rank) so the identity check gets a turn.
    assert "is.controlling_ni" not in confirmed
    assert "is.controlling_ni" in conflicts
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 90          # 90 + 5 == net_income(95)
    assert "is.controlling_ni" not in conflicts


def test_single_value_unaffected_by_the_shortcut_bypass():
    # §2-3: raw candidates already agree (single value) -- takes the normal path,
    # confirmed directly by _resolve() itself, identity check never needed.
    cands = {"is.controlling_ni": [_row(77, "exact"), _row(77, "fuzzy")]}
    confirmed, conflicts = _resolve(cands)
    assert confirmed["is.controlling_ni"] == 77
    assert "is.controlling_ni" not in conflicts
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 77           # unchanged


def test_ambiguous_identity_stays_held_not_guessed():
    # Neither raw candidate satisfies the net_income identity -- 결측 > 오염,
    # stays held rather than guessing.
    cands = {
        "is.controlling_ni": [_row(100, "exact"), _row(90, "normalized")],
        "is.net_income": [_row(999)],
        "is.noncontrolling_ni": [_row(5)],
    }
    confirmed, conflicts = _resolve(cands)
    assert "is.controlling_ni" not in confirmed
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert "is.controlling_ni" not in confirmed
    assert "is.controlling_ni" in conflicts                # still held


def test_no_noncontrolling_line_defaults_to_zero_nci():
    # Wholly-owned consolidation: no is.noncontrolling_ni candidate anywhere.
    cands = {
        "is.controlling_ni": [_row(50, "exact"), _row(40, "normalized")],
        "is.net_income": [_row(40)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 40            # 40 + 0(nci default) == 40


def test_dh_autoware_label_swap_regression_00110583_2022h1():
    # §1-C real filing: the two section labels are literally swapped in the source, so
    # the "포괄" section actually holds the correct NI-attribution figure. A section_path
    # text filter would have picked the wrong one here -- identity (value-anchored) does
    # not care about the label/section and still lands on the right candidate.
    cands = {
        "is.controlling_ni": [_row(-2_314_224_620, "exact"), _row(-2_651_838_029, "normalized")],
        "is.net_income": [_row(-2_667_463_698)],
        "is.noncontrolling_ni": [_row(-15_625_669)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == -2_651_838_029
    assert "is.controlling_ni" not in conflicts


def test_frtek_label_swap_regression_00442561_2017h1():
    # §1-C second real filing: NCI == 0 (wholly-owned), correct figure again sits in the
    # "포괄" section under the swapped labeling.
    cands = {
        "is.controlling_ni": [_row(-2_046_435_530, "exact"), _row(-1_947_034_624, "normalized")],
        "is.net_income": [_row(-1_947_034_624)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == -1_947_034_624


def test_top_stage_corroboration_recovers_when_identity_cannot_confirm():
    # §4-2-2/§4-2-3 Phase 2 finding, real filing 00273420 2015Q1: two independent
    # 'exact'-stage candidates (from the two different sections) agree on the same
    # value -- multi-row corroboration at the best stage. Identity itself can't confirm
    # here (the real noncontrolling_ni value was misclassified into this same candidate
    # pool instead of its own canonical, so the 0-default identity match fails) --
    # this pattern was verified absent from the 404-row known-bug population, so it's
    # safe to trust directly as a fallback.
    cands = {
        "is.controlling_ni": [_row(-1_036_533_085, "exact"), _row(-66_055_549, "fuzzy"),
                               _row(-1_036_533_085, "exact"), _row(-66_055_549, "fuzzy")],
        "is.net_income": [_row(-1_102_588_634)],
    }
    confirmed, conflicts = _resolve(cands)
    assert "is.controlling_ni" not in confirmed        # identity alone can't confirm
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == -1_036_533_085
    assert "is.controlling_ni" not in conflicts


def test_lone_top_stage_candidate_not_corroborated_stays_held():
    # The dangerous §1-A pattern: exactly one row reaches the top stage, no second row
    # to corroborate it (and here is.net_income is entirely absent, so identity can't
    # even attempt). The fallback must NOT fire -- 결측 > 오염.
    cands = {"is.controlling_ni": [_row(100, "exact"), _row(90, "normalized")]}
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert "is.controlling_ni" not in confirmed
    assert "is.controlling_ni" in conflicts


def test_ebt_minus_tax_anchors_identity_when_net_income_line_missing():
    # §A, real filing 00107987 2022FY: the body has no explicit '당기순이익' total line
    # at all (goes straight from tax expense to the attribution breakdown), but EBT and
    # tax_expense are both unambiguous, so their difference anchors the same identity.
    cands = {
        "is.controlling_ni": [_row(47_259_915_285, "exact"), _row(47_099_436_786, "normalized")],
        "is.noncontrolling_ni": [_row(-150_575_018, "exact"), _row(-130_166_324, "exact")],
        "is.ebt": [_row(65_209_716_196)],
        "is.tax_expense": [_row(18_100_375_929)],
        # is.net_income: deliberately absent
    }
    confirmed, conflicts = _resolve(cands)
    assert "is.net_income" not in confirmed
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 47_259_915_285
    assert confirmed["is.noncontrolling_ni"] == -150_575_018


def test_zero_nci_tried_even_when_a_noisy_candidate_exists():
    # §B, real filing 00123541 2021FY: controlling_ni alone already equals net_income
    # exactly (true NCI is 0/negligible), but a small unrelated value happened to get
    # mapped into is.noncontrolling_ni too -- must not block trying 0 as well.
    cands = {
        "is.controlling_ni": [_row(-908_719_386, "exact"), _row(-2_876_306_428, "fuzzy")],
        "is.noncontrolling_ni": [_row(-1_929_765, "exact")],
        "is.net_income": [_row(-908_719_386)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == -908_719_386


def test_epsilon_tolerance_recovers_one_won_rounding_gap():
    # §C, real filing 00530556 2023Q3: the correct pairing is off by exactly 1 won from
    # net_income (source-side rounding between separately printed cells), so the exact
    # match fails but a unique near-match within tolerance succeeds.
    cands = {
        "is.controlling_ni": [_row(-17_680_335_054, "exact"), _row(-17_575_768_786, "fuzzy")],
        "is.noncontrolling_ni": [_row(-672_852_214, "exact"), _row(-672_852_214, "fuzzy")],
        "is.net_income": [_row(-18_353_187_267)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == -17_680_335_054


def test_two_pairs_both_matching_exactly_stays_ambiguous_not_guessed():
    # §C guard, real filing 01025644 2024Q1: two independent candidate pairs BOTH land on
    # net_income exactly (a genuine coincidence -- both sections' figures are internally
    # consistent to the won). Must NOT epsilon-relax further or pick either -- ambiguous
    # stays held.
    cands = {
        "is.controlling_ni": [_row(-3_967_168_840, "exact"), _row(-3_967_168_839, "exact")],
        "is.noncontrolling_ni": [_row(-204_635_031, "exact"), _row(-204_635_032, "exact")],
        "is.net_income": [_row(-4_171_803_871)],
    }
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert "is.controlling_ni" not in confirmed
    assert "is.controlling_ni" in conflicts
