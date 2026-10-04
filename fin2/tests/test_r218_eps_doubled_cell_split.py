"""R218 regression tests - two EPS lines whose values the source XML joined into one cell.

Old-layout filings print `기본및희석주당경상이익 / 기본및희석주당순이익` as ONE row and the XML
cell holds both values concatenated ("182" + "182" -> "182182"). Only the unambiguous shape is
split: exactly two EPS items in the label, no per-period text in the label, and every amount
cell of the row made of two identical halves.

Run: pytest fin2/tests/test_r218_eps_doubled_cell_split.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import (                                   # noqa: E402
    _EpsAmount, _eps_label_has_two_items, _halve_doubled_eps_amounts,
    extract_report_lines,
)

_OSUNG_2004H1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00350048_오성첨단소재/half/2004/20040813000222.xml"
)


def _amts(*vals):
    return [None if v is None else _EpsAmount(v) for v in vals]


def test_two_item_labels_are_recognised():
    assert _eps_label_has_two_items("기본및희석주당경상이익기본및희석주당순이익")
    assert _eps_label_has_two_items("(주당경상이익 : 원) (주당 순 이 익 : 원)")
    assert _eps_label_has_two_items("ⅩⅠ. 주당손익   주당경상이익   주당순이익")


def test_ambiguous_labels_are_left_alone():
    # basic + diluted under one label is ONE value (11 stays 11), and basic/diluted pairs are not split
    assert not _eps_label_has_two_items("1. 기본주당이익 및 희석주당이익")
    assert not _eps_label_has_two_items("ⅩⅠ. 주당순이익     기본주당순이익     희석주당순이익")
    assert _halve_doubled_eps_amounts(_amts(11)) is not None
    assert not _eps_label_has_two_items("기본주당이익(손실)")
    assert not _eps_label_has_two_items("보통주당기기본주당이익(손실)")
    assert not _eps_label_has_two_items("(주당경상이익 : 당분기53원, 전분기101원)(주당순이익 : 당분기53원)")
    assert not _eps_label_has_two_items("기본주당경상이익기본주당순이익희석주당경상이익희석주당순이익")


def test_all_doubled_cells_are_halved():
    out = _halve_doubled_eps_amounts(_amts(182182, 341341, None, 9090, -4646))
    assert [None if a is None else int(a) for a in out] == [182, 341, None, 90, -46]


def test_mixed_row_is_unchanged():
    row = _amts(182182, 341, 171171)
    assert _halve_doubled_eps_amounts(row) is row
    row = _amts(394391, 255255)
    assert _halve_doubled_eps_amounts(row) is row


def test_osung_2004h1_values_are_split():
    if not _OSUNG_2004H1.exists():
        return
    lines = extract_report_lines(
        _OSUNG_2004H1, rcept_no="20040813000222", corp_code="00350048",
        report_fiscal_year=2004, report_fiscal_period="H1",
    )
    vals = sorted(int(l.value_won) for l in lines
                  if (l.source_ref or "").startswith("eps/") and "경상이익" in (l.label_raw or ""))
    assert vals, "EPS rows missing"
    # cumulative columns of the source row are 341341 / 294294 (two joined values each)
    assert vals == [294, 341]


def test_layer3_drops_per_share_candidates_of_one_million_or_more():
    """R218: a header row ('주당손익' = 분기총포괄이익 280,029,785) must not become is.eps_basic."""
    from fin2.layer3.combine import _map_rows

    def row(label, won):
        return {"statement": "IS", "basis": "separate", "label_raw": label, "value_won": won,
                "value_exact": None, "eps_row": True, "node_role": None,
                "section_path": "주당손익", "table_seq": 0, "is_cumulative": False}

    cands = _map_rows([row("기본주당이익", 458), row("주당이익", 5_890_065)], "Q1", "separate", ["IS"])
    assert [c["value"] for c in cands.get("is.eps_basic", [])] == [458]
