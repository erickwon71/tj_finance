"""R310 - an amendment that restates a cell and changes its label or section path (pure, fake session).

제일엠앤에스 2024FY: '자산총계' -> '자본총계 (E=C+D)', '부채총계' -> '부채총계 (A)'; 이오플로우 2024FY: 'Ⅰ.매출액' -> '수익'.
The earlier cell takes the restated value when the table lines up row by row with the earlier one.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3 import combine  # noqa: E402
from fin2.layer3.combine import build_merged_lines  # noqa: E402

_CHAIN = [("orig", False), ("amd1", True), ("amd2", True)]


def _bs(values, labels):
    return [("BS", "consolidated", 0, None, lab, val, "S", 0, False, None, False, None, i)
            for i, (lab, val) in enumerate(zip(labels, values))]


_BASE_LABELS = ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본금", "이익잉여금", "자본총계"]
_ROWS = {
    "orig": _bs([10, 20, 30, 12, 8, 20, 5, 5, 10], _BASE_LABELS),
    # restated values; the total rows are printed under other labels
    "amd1": _bs([11, 22, 33, 13, 9, 22, 5, 6, 11],
                ["유동자산", "비유동자산", "자본총계 (E=C+D)", "유동부채", "비유동부채", "부채총계 (A)", "자본금", "이익잉여금", "자본총계 (D)"]),
    # a second amendment repeats the first one for the totals
    "amd2": _bs([11, 22, 33, 13, 9, 22, 5, 6, 11],
                ["유동자산", "비유동자산", "자본총계 (E=C+D)", "유동부채", "비유동부채", "부채총계 (A)", "자본금", "이익잉여금", "자본총계 (D)"]),
}


class _Result:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


class _FakeSession:
    def execute(self, stmt, params):
        sql = str(stmt)
        if "FROM filings f" in sql:
            return _Result(_CHAIN)
        if "bool_or(unit_source = 'xbrl')" in sql:
            return _Result([(False, False)])
        return _Result(_ROWS[params["r"]])


def _merged():
    return {c["label_raw"]: c for c in build_merged_lines(_FakeSession(), "X", 2024, "FY")}


def test_restated_cell_under_another_label_updates_the_earlier_cell():
    m = _merged()
    assert m["자산총계"]["value_won"] == 33 and m["자산총계"]["amended"]
    # '(A)' / '(D)' labels map to the grand totals: they come in as amended cells and the stale base loses in _resolve
    assert m["부채총계 (A)"]["value_won"] == 22 and m["부채총계 (A)"]["amended"]
    assert m["자본총계 (D)"]["value_won"] == 11
    assert "자본총계 (E=C+D)" not in m          # the misprint took the place of 자산총계 and restated it
    from fin2.layer3.combine import _FS, _map_label
    assert _map_label("자본총계 (E=C+D)", _FS["BS"]).account_code.startswith("unknown.")
    assert _map_label("부채총계 (A)", _FS["BS"]).account_code == "bs.total_liabilities"


def test_switch_off_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setattr(combine, "_R310_POSITIONAL_RESTATEMENT", False)
    m = _merged()
    assert m["자산총계"]["value_won"] == 30 and "자본총계 (E=C+D)" in m


def test_table_that_does_not_line_up_is_untouched():
    # most rows of the later table map to other accounts than the rows at the same place: not a restatement
    _ROWS["amd1"] = _bs([1, 2, 3, 4, 5, 6, 7, 8, 9],
                        ["자본금", "이익잉여금", "자본총계 (E=C+D)", "유동자산", "비유동자산", "부채총계 (A)", "유동부채", "자산총계", "자본총계 (D)"])
    _ROWS["amd2"] = _ROWS["amd1"]
    try:
        m = _merged()
        assert "자본총계 (E=C+D)" in m and m["자본총계 (E=C+D)"]["value_won"] == 3
        assert m["부채총계"]["value_won"] == 20
    finally:
        _ROWS["amd1"] = _bs([11, 22, 33, 13, 9, 22, 5, 6, 11],
                            ["유동자산", "비유동자산", "자본총계 (E=C+D)", "유동부채", "비유동부채", "부채총계 (A)", "자본금", "이익잉여금", "자본총계 (D)"])
        _ROWS["amd2"] = _ROWS["amd1"]


def test_controlling_equity_wording_drift_drops_the_stale_candidate(monkeypatch):
    # 엔케이젠 2024FY: '지배기업의 소유주에게 귀속되는 자본' (base, exact) vs '지배회사지분' (amended, fuzzy)
    def _r(value, stage, label_raw, amended):
        return {"value": value, "stage": stage, "label_raw": label_raw, "section_path": "자본", "table_seq": 0,
                "amended": amended, "amended_by": "a" if amended else None}

    cands = {"bs.controlling_equity": [_r(-23, "exact", "지배기업의 소유주에게 귀속되는 자본", False),
                                       _r(-25, "fuzzy", "지배회사지분", True)]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["bs.controlling_equity"] == -25


def test_trade_payables_and_other_financial_liabilities_caption_is_trade_payables():
    from fin2.layer3.combine import _FS, _map_label
    for label in ("매입채무및기타금융부채", "매입채무 및 기타금융부채"):
        assert _map_label(label, _FS["BS"]).account_code == "bs.trade_payables"


def _cand(value, stage, label_raw, amended, section="부채>유동부채"):
    return {"value": value, "stage": stage, "label_raw": label_raw, "section_path": section, "table_seq": 0,
            "amended": amended, "amended_by": "a" if amended else None}


def test_r311_value_restated_under_another_label_of_the_same_account_wins(monkeypatch):
    # 제일엠앤에스 separate 2024FY: '매입채무및기타채무' (original, exact) vs '매입채무 및 기타유동채무' (amended, normalized)
    cands = {"bs.trade_payables": [_cand(67, "exact", "매입채무및기타채무", False),
                                   _cand(65, "normalized", "매입채무 및 기타유동채무", True)]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["bs.trade_payables"] == 65
    monkeypatch.setattr(combine, "_R311_SAME_SLOT_RESTATED", False)
    confirmed, _ = combine._resolve(cands)
    assert confirmed["bs.trade_payables"] == 67


def test_r311_two_original_rows_in_the_slot_are_left_alone():
    cands = {"bs.trade_payables": [_cand(67, "exact", "매입채무및기타채무", False),
                                   _cand(9, "exact", "매입채무", False),
                                   _cand(65, "normalized", "매입채무 및 기타유동채무", True)]}
    stale = combine._same_slot_restated_stale_ids(cands["bs.trade_payables"])
    assert stale == set()


def test_r311_a_value_several_times_apart_is_not_a_restatement():
    # 00117212: a component row (11.9B) next to the section total (-943B); 00530413: 1.8B vs a wider aggregate 8.8B
    rows = [_cand(-943, "exact", "투자활동으로 인한 현금흐름", False, "영업활동"),
            _cand(12, "fuzzy", "기타투자활동", True, "영업활동")]
    assert combine._same_slot_restated_stale_ids(rows) == set()


# R310-b - the sign word of a label changes with the value ('영업이익(손실)' -> '영업손실')
def _is(values, labels):
    return [("IS", "consolidated", 0, None, lab, val, "S", 0, False, None, False, None, i)
            for i, (lab, val) in enumerate(zip(labels, values))]


_IS_ROWS = {
    "orig": _is([100, 50, 50, 20, -2, 3, -2, -2, -2],
                ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익(손실)", "금융수익",
                 "법인세비용차감전순이익(손실)", "계속영업이익(손실)", "당기순이익(손실)"]),
    # the amendment prints the loss wording, drops the continuing-operations row and adds the attribution header
    "amd1": _is([60, 30, 30, 10, -1, 2, -1, -1, 0],
                ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업손실", "금융수익",
                 "법인세비용차감전순손실", "당기순손실", "당기순손실의 귀속"]),
}


def _merged_is(monkeypatch=None):
    class _S(_FakeSession):
        def execute(self, stmt, params):
            sql = str(stmt)
            if "FROM filings f" in sql:
                return _Result([("orig", False), ("amd1", True)])
            if "bool_or(unit_source = 'xbrl')" in sql:
                return _Result([(False, False)])
            return _Result(_IS_ROWS[params["r"]])
    return {c["label_raw"]: c for c in build_merged_lines(_S(), "X", 2022, "H1")}


def test_sign_word_variant_restates_the_earlier_cell():
    m = _merged_is()
    assert m["영업이익(손실)"]["value_won"] == -1 and m["영업이익(손실)"]["amended"]
    assert m["당기순이익(손실)"]["value_won"] == -1 and m["당기순이익(손실)"]["amended"]


def test_sign_word_variant_switch_off(monkeypatch):
    monkeypatch.setattr(combine, "_R310B_SIGN_WORD_VARIANT", False)
    m = _merged_is()
    assert m["영업이익(손실)"]["value_won"] == -2 and "영업손실" in m


def test_sign_word_variant_is_not_paired_when_the_printed_sign_changes(monkeypatch):
    # 01577952 2025Q1: '영업이익(손실)' -2.87B -> '영업손실' printed as the amount 2.87B
    rows = dict(_IS_ROWS)
    rows["amd1"] = _is([60, 30, 30, 10, 1, 2, 1, 1, 0], [r[4] for r in _IS_ROWS["amd1"]])
    monkeypatch.setitem(_IS_ROWS, "amd1", rows["amd1"])
    m = _merged_is()
    assert m["영업이익(손실)"]["value_won"] == -2 and "영업손실" in m


# R322 - a row that took part in an R310 pairing is registered at its position, so the next filing can undo it
_R322_LABELS = ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본금", "이익잉여금", "자본총계"]
_R322_SPACED = [lab.replace("부채총계", "부  채  총  계") for lab in _R322_LABELS]


def _r322_rows(values, labels, shift):
    return [("BS", "consolidated", 0, None, lab, val, "S", 0, False, None, False, None, i + shift)
            for i, (lab, val) in enumerate(zip(labels, values))]


_R322_ROWS = {
    "orig": _r322_rows([10, 20, 30, 12, 8, 20, 5, 5, 10], _R322_LABELS, 0),
    # 00392691 2019H1: the first same-day attachment amendment prints another liability total under a letter-spaced
    # label and its rows sit one place further down
    "amd1": _r322_rows([10, 20, 30, 12, 8, 99, 5, 5, 10], _R322_SPACED, 1),
    # the second one prints the original numbers again under the same letter-spaced label
    "amd2": _r322_rows([10, 20, 30, 12, 8, 20, 5, 5, 10], _R322_SPACED, 0),
}


def _merged_r322():
    class _S(_FakeSession):
        def execute(self, stmt, params):
            sql = str(stmt)
            if "FROM filings f" in sql:
                return _Result([("orig", False), ("amd1", False), ("amd2", False)])
            if "bool_or(unit_source = 'xbrl')" in sql:
                return _Result([(False, False)])
            return _Result(_R322_ROWS[params["r"]])
    return {c["label_raw"]: c for c in build_merged_lines(_S(), "X", 2019, "H1")}


def test_second_filing_undoes_a_restatement_paired_by_the_first(monkeypatch):
    assert _merged_r322()["부채총계"]["value_won"] == 20
    monkeypatch.setattr(combine, "_R322_POSITION_AFTER_PAIR", False)
    assert _merged_r322()["부채총계"]["value_won"] == 99


# R323 - the amendment prints the sign word ('영업이익' -> '영업이익(손실)')
_R323_ORIG = _is([100, 50, 50, 20, 15, 3, 14, 14, 14],
                 ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익", "금융수익", "법인세비용차감전순이익", "계속영업이익", "당기순이익"])
_R323_AMD = _is([100, 50, 50, 20, 14, 3, 13, 13, 13],
                ["매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익(손실)", "금융수익", "법인세비용차감전순이익(손실)", "계속영업이익",
                 "당기순이익(손실)"])


def _merged_r323():
    class _S(_FakeSession):
        def execute(self, stmt, params):
            sql = str(stmt)
            if "FROM filings f" in sql:
                return _Result([("orig", False), ("amd1", True)])
            if "bool_or(unit_source = 'xbrl')" in sql:
                return _Result([(False, False)])
            return _Result({"orig": _R323_ORIG, "amd1": _R323_AMD}[params["r"]])
    return {c["label_raw"]: c for c in build_merged_lines(_S(), "X", 2018, "FY")}


def test_new_label_with_the_sign_word_restates_the_earlier_cell(monkeypatch):
    m = _merged_r323()
    assert m["영업이익"]["value_won"] == 14 and m["영업이익"]["amended"] and "영업이익(손실)" not in m
    assert m["당기순이익"]["value_won"] == 13
    monkeypatch.setattr(combine, "_R323_NEW_LABEL_SIGNED", False)
    m = _merged_r323()
    assert m["영업이익"]["value_won"] == 15 and m["영업이익(손실)"]["value_won"] == 14
