"""R262 - a printed 0 beside the amount in a 2-cell period group: the amount is the row's value."""
import glob
from pathlib import Path

import pytest

import parser.xml.table_extractor as te

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_switch_exists():
    assert te._R262_ZERO_BESIDE_AMOUNT is True


def test_eugene_separate_is_operating_expenses():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20170515002940"
    g = glob.glob(str(ROOT / "*" / "00131054*" / "quarter" / "2017" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00131054",
                              report_fiscal_year=2017, report_fiscal_period="Q1", include_notes=False)
    got = {l.value_won for l in ls if l.statement == "IS" and l.basis == "separate"
           and l.col_index == 0 and "영" in l.label_raw and "비" in l.label_raw}
    assert 153054484021 in got
