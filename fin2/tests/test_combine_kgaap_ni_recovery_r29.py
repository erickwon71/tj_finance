"""
T3 (R29) — K-GAAP legacy headline-NI recovery unit tests (pure, DB-independent).

docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §4/§6 T3-3/T3-4.
`_map_rows()` injects a curated headline-NI row (from the T3-2 rekeyed key file) into
`is.net_income`'s candidate pool ONLY when (a) `corp`/`fy` are supplied AND (b) that
canonical has no candidate yet from the normal AccountMapper path (§4-4 (e), conservative
default). Verifies the injection fires for a real curated key (00298377 2003FY separate,
also used as T3-1's source cross-check sample #1), stays scoped to that key (no blanket
label-shape match), and backs off when a candidate already exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _map_rows, _load_kgaap_ni_recovery_keys  # noqa: E402

# Real curated key (also T3-1 source cross-check sample #1, design doc §4-5):
# net_income = 553,204 (thousand won) = pretax(650,375) - tax(97,171), confirmed
# against source XML.
_CORP, _FY, _PERIOD, _BASIS = "00298377", 2003, "FY", "separate"
_KEY = (_CORP, _FY, _PERIOD, _BASIS)
_LABEL = next(iter(_load_kgaap_ni_recovery_keys()[_KEY]))


def _headline_row(label=_LABEL, value=553_204_000, table_seq=0):
    return {"statement": "IS", "basis": _BASIS, "label_raw": label, "value_won": value,
            "node_role": None, "section_path": "IS", "table_seq": table_seq,
            "is_cumulative": False}


def test_curated_key_present_in_recovery_file():
    # Sanity check the fixture itself stays in sync with the T3-2 data file.
    assert _LABEL.startswith("XIII. 당기순이익")


def test_curated_label_injected_as_net_income_candidate():
    rows = [_headline_row()]
    cands = _map_rows(rows, _PERIOD, _BASIS, ("IS",), corp=_CORP, fy=_FY)
    assert "is.net_income" in cands
    assert [c["value"] for c in cands["is.net_income"]] == [553_204_000]
    assert cands["is.net_income"][0]["stage"] == "structural"


def test_no_injection_without_corp_fy_no_op():
    # Callers that don't pass corp/fy (existing behavior) must see nothing new --
    # the AccountMapper alone can't map this giant merged label, so cands is empty.
    rows = [_headline_row()]
    cands = _map_rows(rows, _PERIOD, _BASIS, ("IS",))
    assert "is.net_income" not in cands


def test_same_shape_label_outside_curated_keys_not_injected():
    # Same corp/period/basis, but a label text NOT in the curated set for this key --
    # proves the match is exact-label, not a blanket 'headline NI shape' regex.
    rows = [_headline_row(label="XIII. 당기순이익(주석99) (주당순이익 당기:1원)")]
    cands = _map_rows(rows, _PERIOD, _BASIS, ("IS",), corp=_CORP, fy=_FY)
    assert "is.net_income" not in cands


def test_different_corp_not_injected():
    # Same label text, but corp/fy point at a key that isn't in the curated set --
    # proves the match is keyed by (corp, fy, period, basis), not label text alone.
    rows = [_headline_row()]
    cands = _map_rows(rows, _PERIOD, _BASIS, ("IS",), corp="00000001", fy=_FY)
    assert "is.net_income" not in cands


def test_existing_candidate_blocks_injection():
    # §4-4 (e): if is.net_income already has a candidate from the normal mapping path,
    # the curated injection must NOT fire (conservative default -- trust the existing
    # candidate over this one).
    rows = [
        _headline_row(),
        {"statement": "IS", "basis": _BASIS, "label_raw": "당기순이익",
         "value_won": 999_999_000, "node_role": None, "section_path": "IS",
         "table_seq": 1, "is_cumulative": False},
    ]
    cands = _map_rows(rows, _PERIOD, _BASIS, ("IS",), corp=_CORP, fy=_FY)
    assert "is.net_income" in cands
    values = [c["value"] for c in cands["is.net_income"]]
    assert values == [999_999_000]          # only the normal-path candidate, not both
