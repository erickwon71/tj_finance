"""R345 (2026-11-18): net_debt sums separately printed sibling lines of one debt canonical, only when no
hidden parent / child is suspected (docs/plans/debt_sibling_sum_design_2026-11-18.md)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3 import combine as C


def _r(label, value, sp="부채>비유동부채", seq=1, stage="exact", amended=False):
    return {"label_raw": label, "value": value, "section_path": sp, "table_seq": seq,
            "stage": stage, "amended": amended}


def test_won_and_foreign_siblings_summed():
    # 00159616 2004 FY: both were held, net_debt lost all four lines
    rows = [_r("1.원화장기차입금", 134_683_882_120), _r("2.외화장기차입금", 62_409_121_987)]
    assert C._sum_debt_siblings(rows) == 197_093_004_107


def test_unnumbered_siblings_summed():
    # 01109539 2018 Q1: 장기차입금 + 비유동성장기부채 held
    assert C._sum_debt_siblings([_r("장기차입금", 7_546_200_000),
                                 _r("비유동성장기부채", 36_435_463_654)]) == 43_981_663_654


def test_zero_line_does_not_beat_amount():
    # 00916516 2019 FY: exact '유동성장기차입부채' 0 beat the fuzzy convertible bond 101.5억
    rows = [_r("유동성장기차입부채", 0), _r("유동성장기금융부채", 10_151_098_500, stage="fuzzy")]
    assert C._sum_debt_siblings(rows) == 10_151_098_500


def test_section_path_child_dropped():
    rows = [_r("유동성장기차입금 (주16,29)", 1_008_759_065_905, sp="부채>유동부채"),
            _r("(유동성)장기차입금", 1_001_913_734_747, sp="부채>유동부채>유동성장기차입금 (주16,29)")]
    assert C._sum_debt_siblings(rows) == 1_008_759_065_905


def test_child_of_a_line_on_another_canonical_counts_zero():
    # 00628189 2019 FY: fuzzy put the premium under 유동성장기차입금 on long_term_debt
    rows = [_r("(유동성)장기차입금 상환할증금", 7_101_312_978, sp="부채>유동부채>유동성장기차입금 (주16,29)")]
    assert C._sum_debt_siblings(rows, frozenset({"유동성장기차입금"})) == 0


def test_total_with_details_uses_total():
    # flat K-GAAP: 2.장기차입금 = 가.장기차입금 + 나.외화장기차입금
    rows = [_r("2.장기차입금", 19_354_428_000), _r("가.장기차입금", 18_146_340_000),
            _r("나.외화장기차입금", 1_208_088_000)]
    assert C._sum_debt_siblings(rows) == 19_354_428_000


def test_parent_with_single_child_not_doubled():
    assert C._sum_debt_siblings([_r("2.단기차입금", 4_000_000_000),
                                 _r("나.단기차입금", 4_000_000_000)]) == 4_000_000_000


B = 100_000_000   # 1억


def test_mixed_numbering_gives_up():
    rows = [_r("2.장기차입금", 100 * B), _r("가.외화장기차입금", 30 * B)]
    assert C._sum_debt_siblings(rows) is None


def test_partial_sum_gives_up():
    # 30 = 10 + 20 among four lines -> a hidden subtotal is possible
    rows = [_r("장기차입금", 30 * B), _r("원화차입금", 10 * B), _r("외화차입금", 20 * B), _r("기타차입금", 45 * B)]
    assert C._sum_debt_siblings(rows) is None


def test_other_table_gives_up():
    assert C._sum_debt_siblings([_r("장기차입금", 100 * B, seq=1), _r("외화장기차입금", 30 * B, seq=2)]) is None


def test_same_line_two_values_amended_wins_else_gives_up():
    rows = [_r("장기차입금", 100 * B), _r("장기차입금", 120 * B, amended=True), _r("외화장기차입금", 30 * B)]
    assert C._sum_debt_siblings(rows) == 150 * B
    rows = [_r("장기차입금", 100 * B), _r("장기차입금", 120 * B), _r("외화장기차입금", 30 * B)]
    assert C._sum_debt_siblings(rows) is None


def test_net_debt_overlay_uses_sum_and_falls_back():
    canon = {"bs.long_term_debt": None, "bs.short_term_debt": 5 * B}
    debt_rows = {"bs.long_term_debt": [_r("1.원화장기차입금", 100 * B), _r("2.외화장기차입금", 30 * B)]}
    assert C._additive_debt_for_net_debt(canon, {}, debt_rows) == (5 * B, 130 * B)
    debt_rows = {"bs.long_term_debt": [_r("2.장기차입금", 100 * B), _r("가.외화장기차입금", 30 * B)]}
    assert C._additive_debt_for_net_debt(canon, {}, debt_rows) == (5 * B, None)   # held stays held


def test_switch_off_keeps_old_pick(monkeypatch):
    monkeypatch.setattr(C, "_R345_DEBT_SIBLING_SUM", False)
    debt_rows = {"bs.long_term_debt": [_r("1.원화장기차입금", 100 * B), _r("2.외화장기차입금", 30 * B)]}
    assert C._additive_debt_for_net_debt({"bs.long_term_debt": 100 * B}, {}, debt_rows) == (None, 100 * B)


def test_child_with_the_parent_name_dropped():
    # 00113234 2011 FY separate: 단기차입금 = 단기차입금(원화) + 외화단기차입금 printed under it
    rows = [_r("단기차입금", 150_761_547_000, sp="부채>유동부채"),
            _r("단기차입금", 6_520_000_000, sp="부채>유동부채>단기차입금"),
            _r("외화단기차입금", 144_241_547_000, sp="부채>유동부채>단기차입금", stage="fuzzy")]
    assert C._sum_debt_siblings(rows) == 150_761_547_000


def test_bond_under_borrowing_total_counts_zero():
    # 00110893 2009 FY: 7.사채 under Ⅱ.차입부채 (on short_term_debt) was added a second time
    rows = [_r("7. 사채", 60_000_000_000, sp="Ⅱ. 차입부채")]
    assert C._sum_debt_siblings(rows, frozenset({"차입부채", "차입금"})) == 0


def test_bonds_held_as_assets_are_not_debt():
    # 00164973 2004 FY (securities company): 회사채 under trading / AFS / HTM securities
    rows = [_r("(4) 회 사 채", 19_768_345_324, sp="1. 단기매매증권(주석4)"),
            _r("(5) 회 사 채", 911_857_331_240, sp="2. 매도가능증권(주석5)")]
    assert C._sum_debt_siblings(rows) == 0
    # a liability path that mentions securities stays (short-sold securities are under 부채)
    assert C._sum_debt_siblings([_r("사채", 5 * B, sp="부채>비유동부채")]) == 5 * B


def test_asset_only_part_is_no_part_not_zero():
    # 00113191 2011 H1: only 회사채 held under 매도가능·만기보유증권 -> net_debt stays NULL (R343 judges)
    debt_rows = {"bs.bond": [_r("6.회사채", 378 * B, sp="Ⅱ.유가증권>(2)매도가능증권")]}
    assert C._additive_debt_for_net_debt({"bs.bond": None}, {}, debt_rows) == (None, None)


def test_line_above_total_assets_is_an_asset():
    # 삼성생명 2007 Q1: flat table, no section_path; 가.회사채 / 마.회사채 sit above 자산총계
    rows = [dict(_r("가. 회    사    채", 105_765_000_000, sp=None), row_order=7),
            dict(_r("마. 회    사    채", 3_003_912_000_000, sp=None), row_order=16)]
    assert C._sum_debt_siblings(rows, asset_end={1: 40}) == 0
    below = [dict(_r("1. 사채", 250 * B, sp=None), row_order=55)]
    assert C._sum_debt_siblings(below, asset_end={1: 40}) == 250 * B
