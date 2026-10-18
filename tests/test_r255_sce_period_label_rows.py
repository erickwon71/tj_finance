"""R255 - SCE rows labelled 당기초/전기초/전기말 are balance data rows, not column headers.

제이엘케이 20220318000882 (당기초), 바이오솔루션 20170330000990 (전기초/전기말/당기초).
"""
from pathlib import Path

import pytest

from parser.xml.table_extractor import _header_rule_name

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


@pytest.mark.parametrize("label", ["당기초", "전기초", "전기말", "당기말", "당분기말"])
def test_period_label_is_header_outside_sce(label):
    assert _header_rule_name(label) == "기간라벨"


@pytest.mark.parametrize("label", ["당기초", "전기초", "전기말", "당기말", "당분기말"])
def test_period_label_is_data_row_in_sce(label):
    assert _header_rule_name(label, allow_date_label=True) is None


@pytest.mark.parametrize("rel,rcept,corp,fy,fp,basis,labels", [
    ("KOSDAQ/01153293_제이엘케이/annual/2021/20220318000882.xml", "20220318000882", "01153293", 2021, "FY",
     "consolidated", {"당기초"}),
    ("KOSDAQ/00560982_바이오솔루션/annual/2016/20170330000990.xml", "20170330000990", "00560982", 2016, "FY",
     "separate", {"전기초", "전기말", "당기초"}),
])
def test_balance_rows_are_loaded(rel, rcept, corp, fy, fp, basis, labels):
    from fin2.extract.report_lines import extract_report_lines
    path = ROOT / rel
    if not path.exists():
        pytest.skip("raw report not available")
    lines = extract_report_lines(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                 report_fiscal_period=fp, include_notes=False)
    got = {l.label_raw for l in lines if l.statement == "SCE" and l.basis == basis}
    assert labels <= got
