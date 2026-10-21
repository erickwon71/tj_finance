"""R270 - an EPS cell printed one digit per fragment (`9` + `6`) is one number."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _join_single_digit_fragments as join

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_single_digit_fragments_join():
    assert join("9\n6") == "96"
    assert join("1 2 3") == "123"


def test_other_shapes_untouched():
    assert join("96") == "96"
    assert join("12 3") == "12 3"
    assert join("1 2 3 4 5") == "1 2 3 4 5"
    assert join("9,6") == "9,6"


def test_miraeasset_life_consolidated_basic_eps():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20160516003039"
    g = glob.glob(str(ROOT / "*" / "00112332*" / "quarter" / "2016" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00112332", report_fiscal_year=2016,
                              report_fiscal_period="Q1", include_notes=False)
    got = {(l.basis, l.label_raw, l.col_index): l.value_won for l in ls if l.statement == "IS"}
    assert got[("consolidated", "1. 기본주당순이익", 0)] == 96
