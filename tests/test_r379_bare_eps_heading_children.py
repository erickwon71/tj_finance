"""R379 — `계속영업`/`계속영업과 중단영업` children under a bare `주당이익` heading are won per share.

대한전선 20140515001873 separate IS printed `(614)` (won) under `주당이익`; the table unit (천원)
was multiplied in (-614,000).
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl

RAW = Path(__file__).resolve().parents[1] / "raw_report"


def test_bare_heading_child_is_eps():
    assert rl._is_eps_continuing_child("계속영업과중단영업", "주당이익") is True
    assert rl._is_eps_continuing_child("계속영업", "주당이익>계속영업과 중단영업") is True


def test_net_income_heading_is_not_eps():
    assert rl._is_eps_continuing_child("계속영업", "지배기업주주당기순이익") is False
    assert rl._is_eps_continuing_child("계속영업", "손익계산서") is False


def test_r379_daehan_cable_children_are_won():
    files = glob.glob(str(RAW / "KOSPI/00113207_*/quarter/2014/20140515001873.xml"))
    if not files:
        pytest.skip("original XML is not on disk")
    lines = rl.extract_report_lines(files[0], rcept_no="20140515001873", corp_code="00113207",
                                    report_fiscal_year=2014, report_fiscal_period="Q1")
    cur = {l.label_raw: l.value_won for l in lines if l.statement == "IS" and l.basis == "separate"
           and l.col_index == 0 and l.label_raw.startswith("계속영업")}
    assert cur == {"계속영업과 중단영업": -614, "계속영업": -614}
