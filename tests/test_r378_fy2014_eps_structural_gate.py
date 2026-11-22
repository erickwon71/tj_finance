"""R378 — the EPS structural rules (R145/R239) apply from FY2014.

SK텔레콤 20141114001414 separate IS: the EPS path printed 11,303 (won) but the main path added a x10^6 ghost
row (IS_S/기본주당순이익 = 11,303,000,000). LS 20150331003634 consolidated IS: the `계속영업` / `계속영업과
중단영업` children of 주당이익 were multiplied by the table unit (백만원) instead of read as won per share.
"""
import glob
from pathlib import Path

import pytest

from fin2.extract import report_lines as rl

RAW = Path(__file__).resolve().parents[1] / "raw_report"


def _extract(pattern, rcept, corp, fy, fp):
    files = glob.glob(str(RAW / pattern))
    if not files:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(files[0], rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=fp)


def test_gate_starts_at_fy2014():
    assert rl._EPS_STRUCTURAL_RULE_MIN_FY == 2014


def test_fy2013_label_rule_stays_literal():
    # FY2013 keeps the literal-substring behaviour: a label without `주당` is not EPS even under a 주당 section.
    assert rl._is_eps_label("계속영업", section_path="주당이익>기본주당이익", report_fiscal_year=2013) is False
    assert rl._is_eps_label("기본주당순이익", section_path=None, report_fiscal_year=2013) is True


def test_fy2014_structural_label_rule_applies():
    # `지배기업주주당기순이익(손실)` is net income, not EPS: the structural rule rejects it from FY2014.
    assert rl._is_eps_label("지배기업주주당기순이익(손실)", section_path=None, report_fiscal_year=2014) is False
    assert rl._is_eps_label("기본주당순이익", section_path=None, report_fiscal_year=2014) is True


def test_r378_sk_telecom_separate_is_has_no_million_ghost_rows():
    lines = _extract("KOSPI/00159023_*/quarter/2014/20141114001414.xml", "20141114001414", "00159023", 2014, "Q3")
    sep = [l for l in lines if l.statement == "IS" and l.basis == "separate" and "주당순이익" in l.label_raw
           and l.col_index == 0]
    assert sep and all(l.value_won == 11303 for l in sep)
    assert not any(l.source_ref and l.source_ref.startswith("IS_S/") for l in sep)


def test_r378_ls_eps_children_are_won_per_share():
    lines = _extract("KOSPI/00105952_LS/annual/2014/20150331003634.xml", "20150331003634", "00105952", 2014, "FY")
    cur = {l.label_raw: l.value_won for l in lines
           if l.statement == "IS" and l.basis == "consolidated" and l.col_index == 0
           and (l.section_path or "").startswith("주당이익")}
    assert cur["계속영업과 중단영업"] == 1620
    assert cur["계속영업"] == 2345
