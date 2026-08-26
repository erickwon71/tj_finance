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
    _derive_net_income_from_continuing_discontinued,
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


def test_structural_still_pools_continuing_operations_component_section():
    # ★2026-08-25(DRB동일 00118266 FY2012 실제 형태 — account_mapper.py '계속영업'
    # 귀속 가드 확장의 후속 발견 및 되돌림, 기록용 회귀 테스트): section_path=
    # '계속영업당기순이익'인 성분(부분)값도 이 함수는 여전히 후보 풀에 넣는다
    # (일부러 배제하지 않음 — 배제 시도가 시알홀딩스 00148984 FY2015 에서 새 회귀를
    # 유발함을 확인하고 되돌렸다, combine.py 인접 주석 참고). 이 테스트는 그 되돌림
    # 상태(=현재 의도된 동작)를 고정한다.
    rows = [
        _merged_row("IS", "지배기업의 소유주에 귀속될 계속영업당기순이익", 18_327_708_908,
                    section_path="계속영업당기순이익"),
        _merged_row("IS", "비지배지분에 귀속될 계속영업당기순이익", -35_414_062,
                    section_path="계속영업당기순이익"),
    ]
    extra = _ni_attribution_structural_candidates(rows, period="FY", basis="consolidated")
    assert [r["value"] for r in extra["is.controlling_ni"]] == [18_327_708_908]
    assert [r["value"] for r in extra["is.noncontrolling_ni"]] == [-35_414_062]


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
    # ★2026-08-22 update: account_mapper no longer maps the bare '지배기업 소유주지분' label
    # to is.controlling_ni at all (see parser/common/account_mapper.py's bare-지배지분 guard,
    # P1C 잔여회귀 조사) -- it's structurally excluded here too (section_path says '포괄손익의
    # 귀속', not a net-income attribution section), so the OCI value (9,312,323) no longer
    # enters is.controlling_ni's candidate pool at all. Previously it entered via the label
    # mapper alone and had to be out-voted by the structural candidate below; now it's simply
    # never a candidate -- assert the structural candidate is present and the OCI value is not.
    assert 8_028_407 in {r["value"] for r in cands["is.controlling_ni"]}
    assert 9_312_323 not in {r["value"] for r in cands["is.controlling_ni"]}
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 8_028_407   # correct, not the OCI value


# ---------------------------------------------------------------------------
# _derive_net_income_from_continuing_discontinued() — R44 §B net_income anchor
# (2026-08-25), docs/plans/gateb_r44_resolve_redesign_2026-08-25.md §3.
# ---------------------------------------------------------------------------

def test_continuing_discontinued_anchor_sums_when_no_headline_to_check():
    # DRB동일 00118266 FY2012 shape: no plain (unqualified) headline net-income line
    # exists at all -- only the continuing-only and discontinued-only company-wide
    # totals. Nothing to contradict the sum, so it's trusted.
    rows = [
        _merged_row("IS", "법인세비용차감전순이익(손실)", 23_739_991_222, section_path=None),
        _merged_row("IS", "법인세비용", 5_447_696_376, section_path=None),
        _merged_row("IS", "계속영업당기순이익", 18_292_294_846, section_path=None),
        _merged_row("IS", "중단영업당기순이익", 11_585_080_216, section_path=None),
    ]
    anchor = _derive_net_income_from_continuing_discontinued(rows, period="FY", basis="consolidated")
    assert anchor == 29_877_375_062


def test_continuing_discontinued_anchor_suppressed_when_headline_disagrees():
    # 00401731 2011H1 shape: a plain headline line ALSO exists, and it does NOT
    # include the '중단영업' line (a static, non-accumulating figure -- this filer's
    # convention excludes it from net income). The anchor must self-suppress (None)
    # rather than confidently sum to the wrong total.
    rows = [
        _merged_row("IS", "법인세비용차감전순이익(손실)", 188_185_000_000, section_path=None),
        _merged_row("IS", "계속영업이익(손실)", 92_672_000_000, section_path=None),
        _merged_row("IS", "중단영업이익(손실)", 847_734_000_000, section_path=None),
        _merged_row("IS", "반기(당기)순이익(손실)", 92_672_000_000, section_path=None),
    ]
    anchor = _derive_net_income_from_continuing_discontinued(rows, period="H1", basis="consolidated")
    assert anchor is None


def test_continuing_discontinued_anchor_survives_when_headline_agrees():
    # Headline exists and DOES agree with the continuing+discontinued sum -- not
    # suppressed (redundant confirmation, not a contradiction).
    rows = [
        _merged_row("IS", "계속영업순이익(손실)", 100, section_path=None),
        _merged_row("IS", "중단영업순이익(손실)", 20, section_path=None),
        _merged_row("IS", "당기순이익(손실)", 120, section_path=None),
    ]
    anchor = _derive_net_income_from_continuing_discontinued(rows, period="FY", basis="consolidated")
    assert anchor == 120


def test_continuing_discontinued_anchor_ignores_subtotals_in_headline_check():
    # ★2026-08-25 (00401731 실측 반례 발견 중 발견한 별개 결함): the headline
    # cross-check must require '순이익/순손실/순손익' specifically, not the broader
    # '이익/손실/손익' set used for the 계속/중단 scan -- otherwise 매출총이익(gross
    # profit)/영업이익(operating income) subtotals falsely look like competing
    # "headlines", make the pick ambiguous, and (bug, now fixed) an ambiguous
    # headline used to be silently treated as "no headline" instead of "don't
    # trust either" -- letting a wrong sum through uncontested.
    rows = [
        _merged_row("IS", "매출총이익", 999_999, section_path=None),
        _merged_row("IS", "영업이익(손실)", 888_888, section_path=None),
        _merged_row("IS", "계속영업이익(손실)", 100, section_path=None),
        _merged_row("IS", "중단영업이익(손실)", 20, section_path=None),
        _merged_row("IS", "반기(당기)순이익(손실)", 100, section_path=None),  # excludes 중단
    ]
    anchor = _derive_net_income_from_continuing_discontinued(rows, period="H1", basis="consolidated")
    assert anchor is None  # headline(100) != sum(120) -> suppressed, not fooled into passing


def test_continuing_discontinued_anchor_none_when_either_side_ambiguous():
    rows = [
        _merged_row("IS", "계속영업순이익(손실)", 100, section_path=None),
        _merged_row("IS", "계속영업순이익(손실)", 101, section_path=None, table_seq=1),  # 2 distinct
        _merged_row("IS", "중단영업순이익(손실)", 20, section_path=None),
    ]
    assert _derive_net_income_from_continuing_discontinued(rows, period="FY", basis="consolidated") is None


def test_continuing_discontinued_anchor_suppressed_when_headline_itself_ambiguous():
    # ★2026-08-25 (00103547 2020Q1, R45 1,440-corp 전수 백필 검증 중 발견): "헤드라인
    # 후보 없음"과 "헤드라인 후보가 2개 이상이라 모호함"을 같은 값(None)으로 뭉치면
    # 안 된다 -- 이 필링은 같은 표 안에 '당기순이익(손실)'=2,248,146,338 과
    # '분기순이익(손실)'=223,745,179 이 별개 값으로 동시에 존재한다(원문 자체가
    # 어느 쪽이 "진짜" 헤드라인인지 라벨만으로 모호함). 합(cont+disc)이 우연히 그중
    # 하나와 같다는 것이 그 후보가 맞다는 증거가 되지 못하므로, 헤드라인 후보가
    # 2개 이상이면 무조건 억제한다(정확히 0개일 때만 대조할 게 없다고 보고 신뢰).
    rows = [
        _merged_row("IS", "계속영업이익(손실)", 466_367_498, section_path=None),
        _merged_row("IS", "중단영업이익(손실)", -242_622_319, section_path=None),
        _merged_row("IS", "당기순이익(손실)", 2_248_146_338, section_path=None),
        _merged_row("IS", "분기순이익(손실)", 223_745_179, section_path=None),  # == sum, coincidence
    ]
    anchor = _derive_net_income_from_continuing_discontinued(rows, period="Q1", basis="consolidated")
    assert anchor is None


def test_continuing_discontinued_anchor_takes_priority_over_ebt_tax_end_to_end():
    # Full regression, DRB동일 00118266 FY2012 real shape: the EBT-tax fallback (§A)
    # is itself continuing-only-scoped (no textual marker at all -- the original
    # bug) and would confidently confirm the WRONG (continuing-only) attribution
    # pair. §B's anchor must win instead, through the real _map_rows()/_resolve()/
    # _resolve_ni_attribution() pipeline (not just the helper in isolation).
    rows = [
        _merged_row("IS", "법인세비용차감전순이익(손실)", 23_739_991_222, section_path=None),
        _merged_row("IS", "법인세비용", 5_447_696_376, section_path=None),
        _merged_row("IS", "계속영업당기순이익", 18_292_294_846, section_path=None),
        _merged_row("IS", "중단영업당기순이익", 11_585_080_216, section_path=None),
        _merged_row("IS", "지배기업의 소유주에 귀속될 계속영업당기순이익", 18_327_708_908,
                    section_path="계속영업당기순이익"),
        _merged_row("IS", "비지배지분에 귀속될 계속영업당기순이익", -35_414_062,
                    section_path="계속영업당기순이익"),
        _merged_row("IS", "지배기업의 소유주에게 귀속되는 당기순이익(손실)", 29_912_789_124,
                    section_path="당기순이익(손실)"),
        _merged_row("IS", "비지배지분에 귀속되는 당기순이익(손실)", -35_414_062,
                    section_path="당기순이익(손실)"),
    ]
    cands = _map_rows(rows, period="FY", basis="consolidated", statements=("IS",))
    assert "__ni_total_anchor__" in cands
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 29_912_789_124   # headline, not the continuing-only 18.3B
    assert confirmed["is.noncontrolling_ni"] == -35_414_062


def test_ebt_tax_fallback_recovers_when_b_anchor_matches_nothing_end_to_end():
    # ★2026-08-25, found in the R45 436->1,440-corp full backfill verification
    # (00238782 2014Q3, docs/plans/gateb_r44_resolve_redesign_2026-08-25.md §3.6):
    # this filer has NO plain headline line at all (so §B's self-suppression check
    # in _derive_net_income_from_continuing_discontinued never triggers), yet its
    # own controlling/noncontrolling attribution breakdown turns out to be
    # continuing-only-scoped too (sums to the continuing-only total, not
    # continuing+discontinued) -- §B's anchor (cont+disc) matches NOTHING in the
    # actual candidate pool. An earlier "§B replaces §A outright" design left this
    # noncontrolling_ni held (silently defaulting to 0 downstream) instead of
    # falling back to try §A (EBT−tax), which DOES match here since EBT is
    # ALSO continuing-only-scoped for this same filer -- consistently, unlike
    # DRB동일 where §A's EBT is continuing-only-scoped while the real controlling_ni
    # candidate pool contains the true (combined) headline separately. §B must be
    # tried FIRST but fall back to §A when §B matches nothing at all, not stay held.
    rows = [
        _merged_row("IS", "XI.법인세비용차감전순이익(손실)", 100_643_704_266, section_path=None),
        _merged_row("IS", "XⅡ.법인세비용", 25_819_361_707, section_path=None),
        _merged_row("IS", "XⅢ.계속영업이익(손실)", 74_824_342_559, section_path=None),
        _merged_row("IS", "XIV.중단영업이익(손실)", -1_173_030_291, section_path=None),
        _merged_row("IS", "(1)지배기업소유주지분", 17_676_181_488, section_path="XV.당기순이익"),
        _merged_row("IS", "(2)비지배지분", 57_148_161_071, section_path="XV.당기순이익"),
        # TCI-section bare '비지배지분' bleeds into the same is.noncontrolling_ni
        # pool via account_mapper's fuzzy match (no '귀속' qualifier at all on
        # either section's label -- the disambiguating '포괄' wording lives only
        # in section_path, which account_mapper's per-row label match never sees).
        _merged_row("IS", "(1)지배기업소유주지분", 16_653_666_730, section_path="XVII.총포괄이익"),
        _merged_row("IS", "(2)비지배지분", 55_775_684_007, section_path="XVII.총포괄이익"),
    ]
    cands = _map_rows(rows, period="Q3", basis="consolidated", statements=("IS",))
    assert cands["__ni_total_anchor__"][0]["value"] == 73_651_312_268   # §B anchor exists...
    confirmed, conflicts = _resolve(cands)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    assert confirmed["is.controlling_ni"] == 17_676_181_488
    assert confirmed["is.noncontrolling_ni"] == 57_148_161_071   # ...but §A recovers the real NCI
