"""R389 - EPS row whose label sits in the second cell (numbering column first) of a paired-column table."""
from pathlib import Path

import pytest

from fin2.extract.report_lines import (
    _eps_drop_leading_numbering_cell, extract_report_lines)

_FOUND = sorted(Path("/Users/taejin/Project/tj_finance/raw_report/KOSPI").glob(
    "00122737_*/quarter/2014/20140515001895.viewer.xml"))
_PATH = _FOUND[0] if _FOUND else Path("missing")


def test_drop_numbering_cell_only_before_an_eps_label():
    assert _eps_drop_leading_numbering_cell(["", "기본주당이익", "", "305"]) == ["기본주당이익", "", "305"]
    assert _eps_drop_leading_numbering_cell(["XVI.", "주당순이익(손실) (단위 : 원)"]) == [
        "주당순이익(손실) (단위 : 원)"]
    # a numbering cell before a non-EPS label, and a real label in the first cell, stay as they are
    assert _eps_drop_leading_numbering_cell(["I.", "매출액", "1"]) == ["I.", "매출액", "1"]
    assert _eps_drop_leading_numbering_cell(["기본주당이익", "305"]) == ["기본주당이익", "305"]


@pytest.mark.skipif(not _PATH.exists(), reason="source file not on disk")
def test_panocean_2014q1_eps_is_printed_won_not_table_unit():
    rows = extract_report_lines(
        _PATH, rcept_no="20140515001895", corp_code="00122737",
        report_fiscal_year=2014, report_fiscal_period="Q1")
    eps = {(r.basis, r.col_index): r.value_won
           for r in rows if r.statement == "IS" and "주당" in r.label_raw and r.basis == "separate"}
    assert eps == {("separate", 0): 305, ("separate", 1): -7038}
