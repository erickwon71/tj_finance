"""R281 - a balance-sheet body printed under an income-statement heading is read as BS."""
import glob
from pathlib import Path

import pytest

import fin2.extract.text as te

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
RC = "20191114001034"


def _groups():
    from fin2.extract.report_lines import _parse_xml_file
    g = glob.glob(str(ROOT / "*" / "00109037*" / "quarter" / "2019" / f"{RC}.xml"))
    if not g:
        pytest.skip("raw report not available")
    return te._detect_body_statement_tables(_parse_xml_file(Path(g[0])), "A", True)


def test_switch_exists():
    assert te._R281_BS_BODY_UNDER_IS_HEADING is True


def test_daesung_separate_bs_and_is_are_split():
    groups = _groups()
    assert len(groups["BS_S"]) == 1 and len(groups["IS_S"]) == 1
    is_text = "".join(groups["IS_S"][0][0].itertext())
    assert "영업수익" in is_text and "자산총계" not in is_text


def test_switch_off_keeps_old_behaviour():
    te._R281_BS_BODY_UNDER_IS_HEADING = False
    try:
        groups = _groups()
    finally:
        te._R281_BS_BODY_UNDER_IS_HEADING = True
    assert "BS_S" not in groups
