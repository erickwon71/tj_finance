"""R231 (2026-10-11, user decision A): D&A = the cash-flow add-back. One source only, in order
body CF -> cash-flow note -> nature-of-expense note -> SG&A / component notes -> body IS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fin2.layer3 import combine  # noqa: E402
from fin2.layer3.note_da import _note_da_canonicals_from_rows  # noqa: E402
from parser.common.note_labels import AMORTIZATION, DEPRECIATION, DEPRECIATION_ROU  # noqa: E402


class R:
    def __init__(self, label, value, section, seq, ci=0, col_label="당기", row=0):
        self.section_path, self.table_seq, self.row_order = section, seq, row
        self.col_index, self.col_label, self.label_raw, self.value_won = ci, col_label, label, value


def _jw_2019():
    """JW중외제약 2019 연결 20200330004416 (원): 주석 30 성격별 / 주석 36 현금흐름표."""
    return [R("감가상각비", 14148486000, "30. 비용의 성격별 분류", 106, col_label="당기>합계"),
            R("무형자산상각비", 5416223000, "30. 비용의 성격별 분류", 106, col_label="당기>합계", row=1),
            R("감가상각비", 12573022000, "36. 현금흐름표", 135),
            R("무형자산상각비", 5426796000, "36. 현금흐름표", 135, row=1),
            R("사용권자산상각비", 1937197000, "36. 현금흐름표", 135, row=2)]


def test_cash_flow_note_before_nature_note():
    got, src = _note_da_canonicals_from_rows(_jw_2019(), "FY", with_source=True)
    assert src == "cf_note"
    assert got.get(DEPRECIATION) == 12573022000 and got.get(AMORTIZATION) == 5426796000
    assert got.get(DEPRECIATION_ROU) == 1937197000


def test_tangible_asset_amortization_label_is_depreciation():
    """애경산업 2025H1 20250813000751 현금흐름 주석: '유형자산상각비' = 감가상각비."""
    from parser.common.note_labels import classify_da_label
    assert classify_da_label("유형자산상각비") == DEPRECIATION
    rows = [R("유형자산상각비", 6537320000, "32. 현금흐름표", 121, col_label="당반기"),
            R("무형자산상각비", 644485000, "32. 현금흐름표", 121, col_label="당반기", row=1),
            R("사용권자산 감가상각비(건물)", 586770000, "32. 현금흐름표", 121, col_label="당반기", row=2)]
    got, src = _note_da_canonicals_from_rows(rows, "H1", with_source=True)
    assert src == "cf_note" and got.get(DEPRECIATION) == 6537320000


def test_right_of_use_only_is_not_complete():
    rows = [R("사용권자산상각비", 100, "32. 현금흐름표", 1),
            R("감가상각비", 900, "27. 비용의 성격별 분류", 2)]
    got, src = _note_da_canonicals_from_rows(rows, "FY", with_source=True)
    assert src == "nature_note" and got.get(DEPRECIATION) == 900


def test_nature_note_when_no_cash_flow_note():
    rows = [r for r in _jw_2019() if r.section_path.startswith("30.")]
    got, src = _note_da_canonicals_from_rows(rows, "FY", with_source=True)
    assert src == "nature_note" and got.get(DEPRECIATION) == 14148486000


def _enrich(monkeypatch, confirmed, note=({}, None)):
    monkeypatch.setattr(combine, "select_canonical_rcept", lambda *a, **k: "20200330004416")
    monkeypatch.setattr(combine, "note_da_canonicals", lambda *a, **k: note)
    col = {"operating_income": 100}
    src = combine._apply_enrichment(None, "00000001", 2019, "FY", "consolidated",
                                    dict(confirmed), col, "consolidated", {})
    return col, src


def test_body_cash_flow_wins_and_is_line_is_not_added(monkeypatch):
    col, src = _enrich(monkeypatch, {"cf.depreciation": 50, "is.depreciation": 20},
                       note=({DEPRECIATION: 999}, "cf_note"))
    assert src == "cf_body" and col["da_total"] == 50


def test_note_wins_over_body_income_statement_line(monkeypatch):
    col, src = _enrich(monkeypatch, {"is.depreciation": 20},
                       note=({DEPRECIATION: 70, AMORTIZATION: 10}, "cf_note"))
    assert src == "cf_note" and col["da_total"] == 80


def test_body_income_statement_line_is_the_last_resort(monkeypatch):
    col, src = _enrich(monkeypatch, {"is.depreciation": 20})
    assert src == "is_body" and col["da_total"] == 20
