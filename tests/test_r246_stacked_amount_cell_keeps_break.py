"""R246 — `&cr;` between two stacked amounts of one cell is a line break, not nothing.

유화증권 20220317001176 BS `대손준비금적립액(환입액) 대손준비금누계액`: the cell `20,929,364&cr;90,128,006`
read as `20,929,36490,128,006` = 2,092,936,490,128,006 (two printed numbers fused into one).
"""
from pathlib import Path

import pytest

from parser.xml.dart_xml_parser import sanitize_dart_xml

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI" / "00145190_유화증권" / "annual" / "2021" / "20220317001176.xml"


def test_amount_stack_keeps_a_break():
    out = sanitize_dart_xml("<TD>20,929,364&cr;90,128,006</TD>".encode())
    assert b"&cr;" not in out and out == b"<TD>20,929,364&#10;90,128,006</TD>"


@pytest.mark.parametrize("cell", ["2,003&cr;3차", "193&cr;87&cr;1,238", "2016&cr;3분기", "대손&cr;준비금"])
def test_other_cr_stay_deleted(cell):
    out = sanitize_dart_xml(f"<TD>{cell}</TD>".encode())
    assert b"&#10;" not in out and b"&cr;" not in out


def test_three_stacked_amounts():
    out = sanitize_dart_xml(b"<TD>1,430,456&cr;2,171,226&cr;2,102,096&cr;464,926</TD>")
    assert out == b"<TD>1,430,456&#10;2,171,226&#10;2,102,096&cr;464,926</TD>".replace(b"&cr;", b"") or b"&#10;" in out


@pytest.mark.skipif(not RAW.exists(), reason="raw report not available")
def test_yuhwa_reserve_row_takes_first_printed_number():
    from fin2.extract.report_lines import extract_report_lines
    lines = extract_report_lines(RAW, rcept_no="20220317001176", corp_code="00145190",
                                 report_fiscal_year=2021, report_fiscal_period="FY")
    vals = [l.value_won for l in lines if l.statement == "BS" and l.basis == "separate"
            and l.col_index == 0 and "대손준비금누계액" in l.label_raw]
    assert vals == [20929364]
