"""R283 - THEAD names only the last periods; the heading block lists all of them."""
import glob
from pathlib import Path

import pytest

import parser.xml.table_extractor as te

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
RC = "20150813001306"


def _rows():
    from fin2.extract.report_lines import extract_report_lines
    g = glob.glob(str(ROOT / "*" / "00139834*" / "half" / "2015" / f"{RC}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = extract_report_lines(Path(g[0]), rcept_no=RC, corp_code="00139834", report_fiscal_year=2015,
                              report_fiscal_period="H1", include_notes=False)
    return {(l.label_raw, l.col_index): l.value_won for l in ls
            if l.statement == "IS" and l.basis == "separate" and l.table_seq == 1}


def test_switch_exists():
    assert te._R283_TRUNCATED_PERIOD_HEADER is True


def test_current_period_is_first_column():
    rows = _rows()
    assert rows[("순확정급여부채의 재측정요소", 0)] == -3_577_000
    assert rows[("순확정급여부채의 재측정요소", 2)] == -669_448_000
    assert rows[("(반기)총포괄손익(손실)", 0)] == -16_756_857_000


def test_switch_off_keeps_old_columns():
    te._R283_TRUNCATED_PERIOD_HEADER = False
    try:
        rows = _rows()
    finally:
        te._R283_TRUNCATED_PERIOD_HEADER = True
    assert rows[("순확정급여부채의 재측정요소", 0)] == -669_448_000
