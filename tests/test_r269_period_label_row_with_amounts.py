"""R269 - a row labelled like a period header but printing large comma amounts is a data row."""
import glob
from pathlib import Path

import pytest

from parser.xml.table_extractor import _period_label_row_has_amounts as has

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_amount_cells_make_it_a_data_row():
    assert has("기간라벨", ["당분기말", "259,935,881,418", "280,634,117,429"])
    assert has("기간라벨", ["당기말", "(1,234,567)", ""])


def test_real_headers_stay_headers():
    assert not has("기간라벨", ["당기말", "제 16 기", "제 15 기"])
    assert not has("기간라벨", ["당기말", "2026", "2025"])
    assert not has("기간라벨", ["당기말", "", ""])
    assert not has("기간라벨", ["당기말", "12,345", "6,789"])
    assert not has("날짜", ["2026.03.31", "1,234,567,890"])


def test_netmarble_trade_receivables_printed_as_period_label():
    from fin2.extract.report_lines import extract_report_lines
    rc = "20260514000897"
    g = glob.glob(str(ROOT / "*" / "00904672*" / "quarter" / "2026" / f"{rc}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=rc, corp_code="00904672", report_fiscal_year=2026,
                              report_fiscal_period="Q1", include_notes=False)
    got = {(l.basis, l.label_raw, l.col_index): l.value_won for l in ls if l.statement == "BS"}
    assert got[("consolidated", "당분기말", 0)] == 259935881418
    assert got[("separate", "당분기말", 0)] == 121862229168
