"""R284 - the second physical row of a ROWSPAN label in an SCE table keeps that row's own label."""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
RC = "20240516001809"


def _labels():
    g = glob.glob(str(ROOT / "*" / "00858364*" / "quarter" / "2024" / f"{RC}.xml"))
    if not g:
        pytest.skip("raw report not available")
    ls = rl.extract_report_lines(Path(g[0]), rcept_no=RC, corp_code="00858364", report_fiscal_year=2024,
                                 report_fiscal_period="Q1", include_notes=False)
    return [(l.row_order, l.label_raw) for l in ls
            if l.statement == "SCE" and l.basis == "consolidated" and l.col_index == 3]


def test_switch_exists():
    assert rl._R284_CONTINUATION_ROW_OWN_LABEL is True


def test_continuation_row_has_own_label():
    labels = dict(_labels())
    assert labels[20] == "지분법자본변동>지분법자본변동"
    assert labels[21] == "지분법자본변동>지분법자본변동"
    assert "자본의 변동" not in labels.values() or labels.get(21) != "자본의 변동"


def test_switch_off_keeps_outer_group_label():
    rl._R284_CONTINUATION_ROW_OWN_LABEL = False
    try:
        labels = dict(_labels())
    finally:
        rl._R284_CONTINUATION_ROW_OWN_LABEL = True
    assert labels[21] == "자본의 변동"
