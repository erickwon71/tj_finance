"""R268 - R168/R266 arithmetic proofs accept a one-won rounding gap at 1,000,000 won or more."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _dual_closing_row_proved as closing
from parser.xml.table_extractor import _amounts_equal_within_rounding as eq

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_one_won_gap_only_for_large_amounts():
    assert eq(507_541_361, 507_541_362)
    assert not eq(507_541_360, 507_541_362)
    assert not eq(99, 100)


def test_closing_row_with_rounding_gap():
    assert closing([553_874_570], 46_333_209, 507_541_362)
    assert not closing([553_874_570], 46_333_209, 507_541_364)


def test_teerobotics_separate_bs_product_valuation_allowance():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20180402000209"
    g = glob.glob(str(ROOT / "*" / "00867098*" / "annual" / "2017" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00867098", report_fiscal_year=2017,
                              report_fiscal_period="FY", include_notes=False)
    got = {(l.label_raw, l.col_index): l.value_won for l in ls if l.statement == "BS" and l.basis == "separate"}
    assert got[("제품평가충당금", 0)] == 46333209
