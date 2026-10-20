"""R266 - old [detail, balance] closing row is read when a base above + detail == balance."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _dual_base_row_proved as proved

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_base_plus_signed_detail_equals_balance():
    assert proved([10_537_149_056], -7_004_807_056, 3_532_342_000)
    assert proved([-1_721_130_194], 3_441_286_004, 1_720_155_810)


def test_unprinted_sign_contra_and_window():
    assert proved([100], 30, 70)
    assert proved([5, 100], 30, 70)


def test_not_proved_when_no_base_closes_or_detail_is_zero():
    assert not proved([100], 30, 71)
    assert not proved([], 30, 70)
    assert not proved([70], 0, 70)
    assert not proved(["x"], 30, 70)


def test_teuksoo_construction_separate_bs():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20151116001903"
    g = glob.glob(str(ROOT / "*" / "00186939*" / "quarter" / "2015" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00186939", report_fiscal_year=2015,
                              report_fiscal_period="Q3", include_notes=False)
    got = {(l.label_raw, l.col_index): l.value_won for l in ls if l.statement == "BS" and l.basis == "separate"}
    assert got[("사외적립자산의공정가치", 0)] == -7004807056
    assert got[("장기미지급비용", 0)] == 3441286004
