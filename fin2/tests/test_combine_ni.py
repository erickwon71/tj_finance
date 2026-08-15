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

from fin2.layer3.combine import (  # noqa: E402
    _resolve, _resolve_ni_attribution, _map_rows,
    _ni_attribution_structural_candidates,
)


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


# ---------------------------------------------------------------------------
# _ni_attribution_structural_candidates() — mismap fix (2026-08-15), docs/plans/
# std_v3_controlling_ni_mismap_structural_fix_design_2026-08-15.md §2.
# ---------------------------------------------------------------------------

def _merged_row(statement, label, value, section_path=None, table_seq=0,
                basis="consolidated", is_cumulative=False):
    """Minimal build_merged_lines()-shaped row (subset _map_rows()/
    _ni_attribution_structural_candidates() actually read)."""
    return {"statement": statement, "basis": basis, "label_raw": label,
            "value_won": value, "node_role": None, "section_path": section_path,
            "table_seq": table_seq, "is_cumulative": is_cumulative}


def test_structural_recovers_relabeled_controlling_line_samsung_shape():
    # Real regression shape (삼성전자 00126380 2025Q1): the controlling-interest
    # sub-line under '분기순이익의 귀속' reuses the parent line's own label
    # ('분기순이익') instead of a distinct '지배기업...' label -- AccountMapper's
    # label-only matching sends it to is.net_income, never is.controlling_ni.
    rows = [
        _merged_row("IS", "분기순이익", 8_222_878, section_path=None),
        _merged_row("IS", "분기순이익", 8_028_407, section_path="분기순이익의 귀속"),
        _merged_row("IS", "비지배지분", 194_471, section_path="분기순이익의 귀속"),
        # OCI-section pair (wrong concept) -- must NOT be picked up.
        _merged_row("IS", "지배기업 소유주지분", 9_312_323, section_path="포괄손익의 귀속"),
        _merged_row("IS", "비지배지분", 123_593, section_path="포괄손익의 귀속"),
    ]
    extra = _ni_attribution_structural_candidates(rows, period="Q1", basis="consolidated")
    assert [r["value"] for r in extra["is.controlling_ni"]] == [8_028_407]
    assert [r["value"] for r in extra["is.noncontrolling_ni"]] == [194_471]
    assert extra["is.controlling_ni"][0]["stage"] == "structural"


def test_structural_skips_ambiguous_section_shape():
    # Two '비지배' rows in the same NI-attribution section (malformed/unexpected shape)
    # -- must not guess which one is real, so no candidate is emitted at all.
    rows = [
        _merged_row("IS", "비지배지분A", 10, section_path="당기순이익의 귀속"),
        _merged_row("IS", "비지배지분B", 20, section_path="당기순이익의 귀속"),
        _merged_row("IS", "지배기업 소유주지분", 100, section_path="당기순이익의 귀속"),
    ]
    extra = _ni_attribution_structural_candidates(rows, period="FY", basis="consolidated")
    assert extra == {}


def test_structural_excludes_comprehensive_income_section():
    # A clean 2-row '귀속' section that is NOT net-income attribution (no '순이익' in
    # the section name, comprehensive-income wording only) must not fire.
    rows = [
        _merged_row("IS", "지배기업 소유주지분", 100, section_path="총포괄손익의 귀속"),
        _merged_row("IS", "비지배지분", 5, section_path="총포괄손익의 귀속"),
    ]
    extra = _ni_attribution_structural_candidates(rows, period="FY", basis="consolidated")
    assert extra == {}


def test_structural_interim_keeps_only_cumulative_duplicates():
    # H1/Q3: both a quarterly and a cumulative cell exist for the same line (std_v2
    # convention keeps cumulative only for is./cf.) -- the non-cumulative duplicate
    # must be dropped before section-grouping, or the section would show 4 members
    # instead of 2 and correctly be skipped as ambiguous.
    rows = [
        _merged_row("IS", "당기순이익", 50, section_path="당기순이익의 귀속", is_cumulative=True),
        _merged_row("IS", "당기순이익", 30, section_path="당기순이익의 귀속", is_cumulative=False),
        _merged_row("IS", "비지배지분", 5, section_path="당기순이익의 귀속", is_cumulative=True),
        _merged_row("IS", "비지배지분", 3, section_path="당기순이익의 귀속", is_cumulative=False),
    ]
    extra = _ni_attribution_structural_candidates(rows, period="H1", basis="consolidated")
    assert [r["value"] for r in extra["is.controlling_ni"]] == [50]
    assert [r["value"] for r in extra["is.noncontrolling_ni"]] == [5]


def test_map_rows_wiring_recovers_mismap_end_to_end():
    # Full regression, real Samsung-shape labels run through _map_rows() (real
    # AccountMapper) then _resolve()/_resolve_ni_attribution() (real identity check) --
    # proves the structural candidates actually flip the final answer, not just that
    # the helper function returns something in isolation.
    rows = [
        _merged_row("IS", "법인세비용차감전순이익", 9_151_576, section_path=None),
        _merged_row("IS", "분기순이익", 8_222_878, section_path=None),
        _merged_row("IS", "분기순이익", 8_028_407, section_path="분기순이익의 귀속"),
        _merged_row("IS", "비지배지분", 194_471, section_path="분기순이익의 귀속"),
        _merged_row("IS", "지배기업 소유주지분", 9_312_323, section_path="포괄손익의 귀속"),
        _merged_row("IS", "비지배지분", 123_593, section_path="포괄손익의 귀속"),
    ]
    cands = _map_rows(rows, period="Q1", basis="consolidated", statements=("IS",))
    # Pre-fix behaviour would have left is.controlling_ni with the lone OCI value
    # (9,312,323) auto-confirmed -- assert the structural candidate is present too.
    assert 8_028_407 in {r["value"] for r in cands["is.controlling_ni"]}
    assert 9_312_323 in {r["value"] for r in cands["is.controlling_ni"]}
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 8_028_407   # correct, not the OCI value
