"""R340: securities net operating revenue finds the SG&A total behind an angle-bracket note
ref and under the '인건비 및 기타일반관리비' name; split SG&A lines are not summed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.layer3.industry_profiles as ip  # noqa: E402
from fin2.layer3.industry_profiles import SECURITIES, norm  # noqa: E402


def _lines(*pairs):
    return [{"label_raw": l, "value_won": v} for l, v in pairs]


def test_norm_strips_angle_note_ref():
    assert norm("판매비와관리비<주석33,39>") == "판매비와관리비"
    assert norm("판매비와관리비\n<주석 34,40>") == "판매비와관리비"
    assert norm("수수료수익 \n<주석 26,39,41>") == "수수료수익"
    assert norm("이익(손실)<주석20,38>") == "이익"


def test_norm_keeps_non_note_angle():
    assert norm("<영업수익>") == "<영업수익>"


def test_nh_angle_note_sga_gives_net_revenue():
    is_lines = _lines(("영업수익<주석39>", 11_500), ("판매비와관리비<주석33,39>", 300),
                      ("영업이익<주석39>", 200))
    rev, comp = SECURITIES.compose(is_lines)
    assert rev == 500 and "revenue_basis" not in comp


def test_hanwha_combined_sga_label_gives_net_revenue():
    # 한화투자증권 2026Q1 consolidated
    is_lines = _lines(("영업수익 (주39,40)", 1_659_350), ("인건비 및 기타일반관리비 (주34)", 107_891),
                      ("영업이익 (주40)", 29_649))
    rev, comp = SECURITIES.compose(is_lines)
    assert rev == 29_649 + 107_891 and "revenue_basis" not in comp


def test_split_sga_lines_still_gross_fallback():
    # 한화 2015-2023 / 대신: '인건비' + '기타일반관리비' without a total are not summed
    is_lines = _lines(("영업수익", 1_000), ("7.인건비", 100), ("8.기타일반관리비", 50),
                      ("영업이익", 30))
    rev, comp = SECURITIES.compose(is_lines)
    assert rev == 1_000 and comp["revenue_basis"] == "gross_fallback"


def test_switch_off_restores_old_norm(monkeypatch):
    monkeypatch.setattr(ip, "_R340_ANGLE_NOTE", False)
    assert norm("판매비와관리비<주석33,39>") != "판매비와관리비"
