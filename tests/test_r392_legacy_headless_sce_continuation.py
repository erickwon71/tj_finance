"""R392 - the legacy ("XI. 재무제표 등") walk keeps a second, heading-less SCE table.

Yuanta Securities 20141114000904 prints each equity statement as two physical tables: the FY2012 block under the
heading, then the FY2013 / FY2014 blocks in a table with no heading of its own. The legacy walk took only the
first data table after a heading, so the 2013.4.1 ... 2014.9.30 blocks were never loaded (consolidated + separate).
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl

RAW = Path(__file__).resolve().parents[1] / "raw_report" / "KOSPI"


def _lines():
    files = glob.glob(str(RAW / "00117601_*/quarter/2014/20141114000904.xml"))
    if not files:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(files[0], rcept_no="20141114000904", corp_code="00117601",
                                   report_fiscal_year=2014, report_fiscal_period="Q3")


@pytest.mark.parametrize("basis", ["separate", "consolidated"])
def test_second_sce_table_is_loaded(basis):
    labels = {l.label_raw for l in _lines() if l.statement == "SCE" and l.basis == basis}
    assert any(x.startswith("2013.4.1") for x in labels)
    assert any(x.startswith("2014.09.30") or x.startswith("2014.9.30") for x in labels)


def test_separate_2013_opening_balance_is_printed_value():
    cells = {l.col_index: l.value_won for l in _lines()
             if l.statement == "SCE" and l.basis == "separate" and l.label_raw.startswith("2013.4.1")}
    assert cells[0] == 688490180000
