"""R229 (2026-10-10): a printed label that is the taxonomy's own Korean label resolves to its
concept's canonical when the alias catalog does not place it (or only fuzzily)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fin2.layer3.combine import _map_rows, _map_taxonomy_label  # noqa: E402
from fin2.taxonomy.ko_labels import canonical_for_label  # noqa: E402


def _row(label, value, statement="BS"):
    return {"statement": statement, "basis": "consolidated", "label_raw": label, "value_won": value,
            "value_exact": None, "is_cumulative": False, "node_role": "F", "section_path": "",
            "table_seq": 1}


def test_standard_label_resolves():
    assert canonical_for_label("영업권 이외의 무형자산") == "bs.intangibles"
    assert canonical_for_label("영업권이외의 무형자산 (주12)") == "bs.intangibles"
    assert canonical_for_label("(5)영업권 이외의 무형자산") == "bs.intangibles"


def test_audit_only_concepts_never_name_a_canonical():
    # dart_ShortTermOtherPayables is mapped to bs.trade_payables for the Gate B audit only
    assert canonical_for_label("단기미지급금") is None
    assert canonical_for_label("비유동채무") is None


def test_eps_and_wrong_statement_are_left_alone():
    assert _map_taxonomy_label("기본주당이익(손실)", "is") is None
    assert _map_taxonomy_label("영업권 이외의 무형자산", "is") is None


def test_unmapped_label_becomes_a_candidate():
    cands = _map_rows([_row("영업권 이외의 무형자산", 2_497_967_222)], "FY", "consolidated", ("BS",))
    assert [c["value"] for c in cands["bs.intangibles"]] == [2_497_967_222]


def test_alias_catalog_outranks_a_taxonomy_match():
    from fin2.layer3.combine import _STAGE_RANK
    rows = [_row("자본", 1_393_372_143), _row("자  본  총  계", 27_347_639_325),
            _row("(9)무형자산", 99_345_168_330), _row("(10)영업권 이외의 무형자산", 79_915_583_756)]
    cands = _map_rows(rows, "FY", "consolidated", ("BS",))
    for canon, want in (("bs.total_equity", 27_347_639_325), ("bs.intangibles", 99_345_168_330)):
        best = max(_STAGE_RANK[c["stage"]] for c in cands[canon])
        assert [c["value"] for c in cands[canon] if _STAGE_RANK[c["stage"]] == best] == [want]


def test_taxonomy_beats_a_fuzzy_guess():
    # fuzzy used to place '유동자산 합계' on bs.total_assets
    cands = _map_rows([_row("유동자산 합계", 100)], "FY", "consolidated", ("BS",))
    assert "bs.total_assets" not in cands and [c["value"] for c in cands["bs.current_assets"]] == [100]
