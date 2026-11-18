"""R342 exact-only borrowing aliases and R343 debt-free net_debt (2026-11-18, tj_asset request #6).

R342: labels that fell to unknown kept net_debt NULL for companies that borrow (하이트진로 2025 FY
'차입금(유동)' 640.3B / '차입금(비유동)' 316.4B). They are exact-only: the fuzzy matcher never sees
them, so no existing fuzzy match moves.
R343: net_debt = -cash only when BS and notes both show no borrowings.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from account_maps.bs_accounts import BS_EXACT_ONLY_ACCOUNTS
from parser.common.account_mapper import get_mapper
from fin2.layer3 import combine as C


@pytest.mark.parametrize("label, code", [
    ("유동성 금융기관 차입금(사채 제외)", "bs.short_term_debt"),
    ("유동성 금융기관 차입금(사채 제외) (주1,5,7,9,20)", "bs.short_term_debt"),
    ("(2)유동 금융기관 차입금 및 비유동 금융기관 차입금(사채 제외)의 유동성 대체 부분", "bs.short_term_debt"),
    ("차입금(유동)", "bs.short_term_debt"),
    ("차입금등(유동)", "bs.short_term_debt"),
    ("차입부채(유동)", "bs.short_term_debt"),
    ("단기 및 유동성차입금", "bs.short_term_debt"),
    ("비유동성 금융기관 차입금(사채 제외)", "bs.long_term_debt"),
    ("비유동 금융기관 차입금(사채 제외)", "bs.long_term_debt"),
    ("차입금(비유동) (주17,31,32,33,34)", "bs.long_term_debt"),
    ("차입금등(비유동)", "bs.long_term_debt"),
    ("장기 금융기관 차입금(사채 제외)의 유동성 대체 부분", "bs.current_portion_lt_debt"),
])
def test_r342_labels_map(label, code):
    r = get_mapper().map(label, fs_section="bs")
    assert r.account_code == code, (label, r)
    assert r.stage in ("exact", "normalized")


@pytest.mark.parametrize("label, code", [
    # fuzzy results that a plain BS_ACCOUNTS alias would have moved (measured 2026-11-18)
    ("유동성차입금", "bs.current_portion_lt_debt"),
    ("유동 차입금", "bs.short_term_debt"),
    ("비유동성차입금", "bs.long_term_debt"),
])
def test_r342_exact_only_does_not_move_fuzzy(label, code):
    r = get_mapper().map(label, fs_section="bs")
    assert r.account_code == code and r.stage == "fuzzy", (label, r)


def test_r342_exact_only_not_in_fuzzy_pool():
    m = get_mapper()
    pool = {a for pairs in m._aliases_norm_by_code.values() for a, _ in pairs}
    for aliases in BS_EXACT_ONLY_ACCOUNTS.values():
        assert not pool.intersection(aliases)


def _bs(label, value, rcept="R1", basis="consolidated"):
    return {"statement": "BS", "basis": basis, "label_raw": label, "value_won": value,
            "source_rcept": rcept}


class _Session:
    """Stub for the single note_lines count query."""

    def __init__(self, n_rows, n_debt):
        self.n = (n_rows, n_debt)
        self.calls = 0

    def execute(self, *_a, **_k):
        self.calls += 1
        n = self.n

        class _R:
            def one(self):
                return n
        return _R()


_COL = {"cash": 100, "total_liabilities": 500}
_BS_FREE = [_bs("현금및현금성자산", 100), _bs("매입채무", 300), _bs("부채총계", 500)]


def test_r343_debt_free_gives_minus_cash():
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", {}, {}, dict(_COL)) == -100


def test_r343_note_borrowing_keeps_null():
    # 한라캐스트 2025 FY: borrowings inside 기타유동금융부채, visible only in the notes
    assert C._debt_free_net_debt(_Session(50, 3), _BS_FREE, "consolidated", {}, {}, dict(_COL)) is None


def test_r343_notes_missing_keeps_null():
    assert C._debt_free_net_debt(_Session(0, 0), _BS_FREE, "consolidated", {}, {}, dict(_COL)) is None


def test_r343_bs_debt_line_keeps_null_without_query():
    s = _Session(50, 0)
    bs = _BS_FREE + [_bs("전환사채전환권조정", -10)]   # 피노 2025 FY
    assert C._debt_free_net_debt(s, bs, "consolidated", {}, {}, dict(_COL)) is None
    assert s.calls == 0


def test_r343_lease_and_loan_lines_are_not_debt():
    bs = _BS_FREE + [_bs("리스부채", 20), _bs("단기대여금", 5)]
    assert C._debt_free_net_debt(_Session(50, 0), bs, "consolidated", {}, {}, dict(_COL)) == -100


def test_r343_debt_candidate_or_conflict_keeps_null():
    cands = {"bs.short_term_debt": [{"value": 1}]}
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", cands, {}, dict(_COL)) is None
    conflicts = {"bs.bond": [{"value": 1}, {"value": 2}]}
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", {}, conflicts, dict(_COL)) is None


def test_r343_needs_cash_liabilities_and_bs_of_basis():
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "separate", {}, {}, dict(_COL)) is None
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", {}, {},
                                 {"cash": None, "total_liabilities": 500}) is None
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", {}, {},
                                 {"cash": 100, "total_liabilities": None}) is None


def test_r343_derived_net_debt_untouched():
    col = dict(_COL, net_debt=7)
    assert C._debt_free_net_debt(_Session(50, 0), _BS_FREE, "consolidated", {}, {}, col) is None


# R342-b: borrowing labels fuzzy had on the wrong side or on a non-debt canonical
@pytest.mark.parametrize("label, code", [
    ("유동성장기차입부채", "bs.current_portion_lt_debt"),            # was long_term_debt
    ("장기차입부채(유동)", "bs.current_portion_lt_debt"),
    ("유동성장기사채및차입금", "bs.current_portion_lt_debt"),
    ("비유동 금융기관 차입금(사채 제외)의 비유동성 대체 부분", "bs.long_term_debt"),  # was current portion
    ("비유동성장기부채", "bs.long_term_debt"),
    ("비유동차입부채", "bs.long_term_debt"),                           # was the 비유동부채 total
    ("단기차입금및장기차입금(사채포함)의유동성대체부분", "bs.short_term_debt"),
    ("단기차입채무", "bs.short_term_debt"),                            # was trade_payables
])
def test_r342b_corrected(label, code):
    r = get_mapper().map(label, fs_section="bs")
    assert r.account_code == code, (label, r)


def test_r342b_financial_institution_borrowing_detail_unmapped():
    # detail line under 차입부채 > 원화차입금; fuzzy had it on bs.short_term_investment (an asset)
    assert get_mapper().map("금융기관차입금", fs_section="bs").account_code.startswith("unknown.")


# R344: fuzzy may not put a non-borrowing label on a borrowing canonical
@pytest.mark.parametrize("label", [
    "유동성장기미지급금", "유동성장기리스부채", "유동성기타충당부채", "유동성장기계약부채", "유동성장기선수금",
    "유동성사채할인발행차금", "유동성전환사채전환권조정", "유동성신주인수권조정", "장기차입금현재가치할인차금",
    "유동성장기매출채권", "유동성장기채권", "비유동성채무상품", "비유동대여금의비유동성대체부분",
    "신주인수권", "신주인수권부채", "유동성전환우선주부채", "비유동사용권부채", "회사",
])
def test_r344_not_debt_refused(label):
    r = get_mapper().map(label, fs_section="bs")
    assert r.account_code not in C._DEBT_CANONICALS, (label, r)


@pytest.mark.parametrize("label, code", [
    # kept as borrowings: BW written short, redemption premium, rehabilitation / securitised debt, FVTPL CB
    ("신주인수권사채", "bs.warrant_bond"),
    ("신주인수권부사채상환할증금", "bs.warrant_bond"),
    ("유동성회생채무", "bs.current_bond"),
    ("유동성장기유동화채무", "bs.current_portion_lt_debt"),
    ("유동성장기금융부채", "bs.current_portion_lt_debt"),   # 00916516 2019: a convertible bond at FVTPL
    ("장기차입금및장기리스부채", "bs.long_term_debt"),        # combined line keeps the borrowing
    ("유동성장기부채(Current Portion of Long-term Liabilities)", "bs.current_portion_lt_debt"),
])
def test_r344_borrowings_kept(label, code):
    assert get_mapper().map(label, fs_section="bs").account_code == code
