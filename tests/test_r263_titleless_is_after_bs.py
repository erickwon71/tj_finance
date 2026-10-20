"""R263 - an income statement printed with no title right after the balance sheet is read as IS."""
import glob
from pathlib import Path

import pytest

import fin2.extract.text as te

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _rows(corp, kind, year, rc, period):
    from fin2.extract.report_lines import extract_report_lines
    g = glob.glob(str(ROOT / "*" / f"{corp}*" / kind / year / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    return extract_report_lines(Path(g[0]), rcept_no=rc, corp_code=corp, report_fiscal_year=int(year),
                                report_fiscal_period=period, include_notes=False)


def test_switch_exists():
    assert te._R263_TITLELESS_IS_AFTER_BS is True


def test_incar_separate_is_operating_revenue():
    ls = _rows("01013694", "quarter", "2017", "20170516000038", "Q1")
    got = {(l.col_index, l.value_won) for l in ls if l.statement == "IS" and l.basis == "separate"
           and l.label_raw.strip().endswith("영업수익")}
    assert (0, 39696600992) in got and (1, 30915787540) in got


def test_not_applied_when_a_titled_is_follows():
    # 아이로보틱스 20231113000061: a supplementary table precedes the titled IS; it must not be taken.
    from fin2.extract.report_lines import _parse_xml_file
    g = glob.glob(str(ROOT / "*" / "00370200*" / "quarter" / "2023" / "20231113000061.xml"))
    if not g:
        pytest.skip("raw report not available")
    root = _parse_xml_file(Path(g[0]))
    counts = []
    for flag in (False, True):
        te._R263_TITLELESS_IS_AFTER_BS = flag
        counts.append(len(te._detect_body_statement_tables(root, "A", True)["IS_S"]))
    te._R263_TITLELESS_IS_AFTER_BS = True
    assert counts[0] == counts[1]


def test_r264_hanwha_investment_consolidated_sce_under_next_heading():
    ls = _rows("00148610", "quarter", "2020", "20200515000970", "Q1")
    got = {l.value_won for l in ls if l.statement == "SCE" and l.basis == "consolidated"}
    assert 886212555000 in got
