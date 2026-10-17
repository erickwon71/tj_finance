"""R252 - a titleless BS whose header label cell is blank still starts the balance sheet.
R253 - a handwritten (merged-title) statement table declares the section's first unit for sibling tables.

삼성E&A 20231114001229 (2023Q3) consolidated BS; 특수건설 20151116001903 (2015Q3) separate SCE/CF.
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

from fin2.extract.statement_titles import titleless_bs_start

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
SEC = glob.glob(str(ROOT / "KOSPI" / "00126308_삼성E&A" / "quarter" / "2023" / "20231114001229.xml"))
TUK = glob.glob(str(ROOT / "KOSDAQ" / "00186939_특수건설" / "quarter" / "2015" / "20151116001903.xml"))


def _bs(first_cell):
    return etree.fromstring(
        "<TABLE><TBODY>"
        f"<TR><TD>{first_cell}</TD><TD>제1기 3분기말</TD><TD>제0기말</TD></TR>"
        "<TR><TD>자산</TD><TD></TD><TD></TD></TR>"
        "<TR><TD>유동자산</TD><TD>1</TD><TD>2</TD></TR></TBODY></TABLE>")


def test_blank_header_label_cell_starts_bs():
    assert titleless_bs_start(_bs("")) is True


def test_non_header_first_cell_still_rejected():
    assert titleless_bs_start(_bs("유동자산")) is False


def _lines(path, rcept, corp, fy):
    from fin2.extract.report_lines import extract_report_lines
    return extract_report_lines(Path(path), rcept_no=rcept, corp_code=corp,
                                report_fiscal_year=fy, report_fiscal_period="Q3")


@pytest.mark.skipif(not SEC, reason="raw report not available")
def test_samsung_ena_consolidated_bs_loaded():
    got = [l for l in _lines(SEC[0], "20231114001229", "00126308", 2023)
           if l.statement == "BS" and l.basis == "consolidated" and l.col_index == 0]
    assert len(got) >= 50
    assert {l.label_raw: l.value_won for l in got}["유동자산"] == 5655525695819


@pytest.mark.skipif(not TUK, reason="raw report not available")
def test_tuk_cf_and_sce_use_section_unit():
    lines = _lines(TUK[0], "20151116001903", "00186939", 2015)
    cf = {l.label_raw: l.value_won for l in lines
          if l.statement == "CF" and l.basis == "separate" and l.col_index == 0}
    assert cf["영업활동현금흐름"] == -3131886858
    assert any(l.statement == "SCE" and l.basis == "separate" for l in lines)
