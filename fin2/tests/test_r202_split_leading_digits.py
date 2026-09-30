"""R202 — 숫자의 첫 1~2자리가 셀 안에서 떨어져 공백으로 이어진 서식('1 73,918,853,979').

호텔신라 `20220308000990` 별도 CF '소 계' 당기 173,918,853,979 (#85494): 원문은 `<SPAN>1</SPAN><SPAN>73,918,853,979</SPAN>`.
"""
from __future__ import annotations

from pathlib import Path

import parser.common.amount_normalizer as AN
from parser.common.amount_normalizer import parse_amount

_HOTEL = Path(__file__).resolve().parents[2] / "raw_report/KOSPI/00165680_호텔신라/annual/2021/20220308000990.xml"


def test_leading_digits_are_joined_only_when_the_first_group_becomes_three_digits():
    assert parse_amount("1 73,918,853,979") == 173918853979
    assert parse_amount("2\n84,079") == 284079
    assert parse_amount("16 0,000") == 160000
    # first group would not be exactly 3 digits -> two numbers / a note number, never joined
    assert parse_amount("5 1,234,567") is None
    assert parse_amount("12 345,678") is None
    assert parse_amount("1 234") is None
    assert parse_amount("3 45,678 90") is None


def test_switch_off_keeps_the_cell_missing():
    AN._R202_SPLIT_LEADING_DIGITS = False
    try:
        assert parse_amount("1 73,918,853,979") is None
    finally:
        AN._R202_SPLIT_LEADING_DIGITS = True


def test_hotel_shilla_separate_cf_subtotal_present():
    if not _HOTEL.exists():
        return
    from fin2.extract.report_lines import extract_report_lines
    lines = extract_report_lines(str(_HOTEL), rcept_no="20220308000990", corp_code="00165680",
                                 report_fiscal_year=2021, report_fiscal_period="FY", include_notes=False)
    cells = {l.col_index: l.value_won for l in lines if l.statement == "CF" and l.basis == "separate"
             and l.row_order == 25 and l.label_raw == "소 계"}
    assert cells.get(0) == 173918853979 and cells.get(1) == 298519071908
