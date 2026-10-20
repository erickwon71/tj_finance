"""R261 - a leading digit printed apart (`8\n4,153,171`) joins only when the row sum proves it."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _join_split_leading_digit_by_row_sum as join

ROOT = Path(__file__).resolve().parents[1] / "raw_report"

ROW = ["1,062,448,235 ", "-", "(56,356,376)", "8\n4,153,171 ", "(100,869,435)", "989,375,595 "]


def test_joins_when_the_row_sum_closes_only_with_the_joined_value():
    assert join(ROW)[3] == "84,153,171"
    assert join(ROW)[:3] == ROW[:3] and join(ROW)[4:] == ROW[4:]


def test_blank_and_dash_cells_count_as_zero():
    row = ["1,000", "", "-", "8 4,153,171", "84,154,171"]
    assert join(row)[3] == "84,153,171"
    row = ["1,000", "", "8 4,153,171", "", "4,154,171"]     # 1,000 + 84,153,171 != 4,154,171
    assert join(row) == row


def test_not_joined_when_the_sum_does_not_close():
    row = list(ROW)
    row[5] = "989,375,596 "
    assert join(row) == row


def test_not_joined_when_the_second_token_alone_closes_the_row():
    # a note number "8" printed beside the real amount 4,153,171
    row = ["1,000,000", "8 4,153,171", "5,153,171"]
    assert join(row) == row


def test_not_joined_with_two_candidates_or_unreadable_cell():
    row = ["8 4,153,171", "7 4,153,171", "168,306,342"]
    assert join(row) == row
    assert join(["1,000", "8 4,153,171", "abc", "84,154,171"]) == ["1,000", "8 4,153,171", "abc", "84,154,171"]


def test_candidate_must_precede_the_total_cell():
    row = ["84,153,171", "8 4,153,171"]
    assert join(row) == row


def test_yuanta_separate_sce_other_comprehensive_income():
    from fin2.extract.report_lines import extract_report_lines
    for rc, y in (("20160816001407", "2016"), ("20170814001981", "2017")):
        g = glob.glob(str(ROOT / "*" / "00117601*" / "half" / y / f"{rc}.xml"))
        if not g:
            pytest.skip("raw report not available")
        ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00117601",
                                  report_fiscal_year=int(y), report_fiscal_period="H1", include_notes=False)
        got = {l.value_won for l in ls if l.statement == "SCE" and l.basis == "separate"
               and l.col_label == "기타포괄손익누계액"}
        assert 84153171000 in got, rc
