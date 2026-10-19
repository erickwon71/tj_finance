"""R260 - leading digits printed one per fragment (`2 8 6,763,456,363`) join into one amount (R202 multi-fragment variant)."""
import glob
from pathlib import Path

import pytest

from parser.common.amount_normalizer import parse_amount

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def test_one_digit_fragments_join_when_the_first_group_has_three_digits():
    assert parse_amount("2\n8\n6,763,456,363") == 286763456363
    assert parse_amount("2 8 6,763") == 286763


def test_r202_two_token_form_is_unchanged():
    assert parse_amount("1 73,918,853,979") == 173918853979


def test_ambiguous_forms_stay_unreadable():
    assert parse_amount("8\n4,153,171") is None          # a note number may precede the amount
    assert parse_amount("1,000 2,000") is None
    assert parse_amount("2 8 66,763,456") is None         # first group would not be three digits


def test_hyundai_marine_consolidated_operating_income():
    g = glob.glob(str(ROOT / "*" / "00164973*" / "annual" / "2020" / "20210318000755.xml"))
    if not g:
        pytest.skip("raw report not available")
    from fin2.extract.report_lines import extract_report_lines
    ls = extract_report_lines(Path(g[0]), rcept_no="20210318000755", corp_code="00164973",
                              report_fiscal_year=2020, report_fiscal_period="FY", include_notes=False)
    got = {l.value_won for l in ls if l.statement == "IS" and l.basis == "consolidated"
           and l.col_index == 0 and l.label_raw.strip() == "Ⅲ. 영업이익"}
    assert 286763456363 in got
