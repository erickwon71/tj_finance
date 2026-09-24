"""R169 — self-contradictory unit declarations confirmed per (rcept, section) by
`scripts/unit_self_contradiction_scan.py` (docs/PARSING_RULES.md R169).

Real-file tests; each case is skipped when the raw XML is not mounted.
"""
from __future__ import annotations

import json
from pathlib import Path

from fin2.audit.unit_self_contradiction import _decide
from fin2.extract import report_lines as rl
from fin2.extract.report_lines import extract_report_lines

_RAW = Path(__file__).resolve().parents[2] / "raw_report"
_HUGEL_2022_FY = _RAW / "KOSDAQ/00888347_휴젤/annual/2022/20230322000822.xml"
_HANKOOK_TIRE_2022_FY = _RAW / "KOSPI/00937324_한국타이어앤테크놀로지/annual/2022/20230324001066.xml"
_NETMARBLE_2017_FY = _RAW / "KOSPI/00904672_넷마블/annual/2017/20180402005173.xml"
_NH_INVEST_2015_Q3 = _RAW / "KOSPI/00120182_NH투자증권/quarter/2015/20151112000378.xml"


def _rows(lines, statement, basis, col=0):
    return {l.label_raw: l for l in lines
            if l.statement == statement and l.basis == basis and (l.col_index or 0) == col}


def test_r169_hugel_declared_million_won_cells_already_won():
    """휴젤 2022FY — every statement declares "(단위 : 백만원)" but prints 원 amounts.
    Before R169 the 1경원 cap dropped every total (연결 BS 12 of 115 rows survived)
    and the survivors were stored x10^6."""
    if not _HUGEL_2022_FY.exists():
        return
    lines = extract_report_lines(
        _HUGEL_2022_FY, rcept_no="20230322000822", corp_code="00888347",
        report_fiscal_year=2022, report_fiscal_period="FY")
    bs = _rows(lines, "BS", "consolidated")
    assert bs["유동자산"].value_won == 617_863_083_758
    assert bs["재고자산 (주7)"].value_won == 26_906_646_505       # issue #46811
    assert bs["유동자산"].unit_source == "proved_unit"
    # SCE is covered too (R132 never reached the SCE emitter).
    sce = [l for l in lines if l.statement == "SCE" and l.value_won is not None]
    assert sce and max(abs(l.value_won) for l in sce) < 10**15
    assert {l.unit_source for l in sce} == {"proved_unit"}


def test_r169_hankook_tire_declared_thousand_won_cells_already_won():
    """한국타이어 2022FY — IS declares 천원 while cells are 원 (매출액 8.39조원);
    연결 자산총계 12.58조원 was dropped by the cap under the declared unit."""
    if not _HANKOOK_TIRE_2022_FY.exists():
        return
    lines = extract_report_lines(
        _HANKOOK_TIRE_2022_FY, rcept_no="20230324001066", corp_code="00937324",
        report_fiscal_year=2022, report_fiscal_period="FY")
    assert _rows(lines, "BS", "consolidated")["자산총계"].value_won == 12_581_364_159_005
    assert _rows(lines, "IS", "consolidated")["매출액"].value_won == 8_394_203_036_511


def test_r169_r132_rcept_sce_no_longer_scaled():
    """넷마블 2017FY (R132 manual list) — SCE kept x10^6 values because the override was
    applied to BS/IS/CF only."""
    if not _NETMARBLE_2017_FY.exists():
        return
    lines = extract_report_lines(
        _NETMARBLE_2017_FY, rcept_no="20180402005173", corp_code="00904672",
        report_fiscal_year=2017, report_fiscal_period="FY")
    sce = [l for l in lines if l.statement == "SCE" and l.value_won is not None]
    assert sce and max(abs(l.value_won) for l in sce) < 10**15
    assert {l.unit_source for l in sce} == {"manual_unit"}


def test_r169_genuine_million_won_securities_cf_untouched():
    """NH투자증권 CF really is in 백만원 (gross trading flows exceed 1,000조원). The scan
    finds matches only at the declared unit, so it must stay declared."""
    assert "20151112000378" not in rl._PROVED_UNIT_OVERRIDES
    if not _NH_INVEST_2015_Q3.exists():
        return
    lines = extract_report_lines(
        _NH_INVEST_2015_Q3, rcept_no="20151112000378", corp_code="00120182",
        report_fiscal_year=2015, report_fiscal_period="Q3")
    cf = [l for l in lines if l.statement == "CF" and l.value_won is not None
          and not (l.source_ref or "").startswith("eps/")]
    assert cf and {l.unit_source for l in cf} <= {"declared", "col_money", "inherited"}


def test_r169_decision_rule():
    decide = _decide
    assert decide({1: 82, 1_000: 1, 1_000_000: 0}) == 1       # one round-number coincidence
    assert decide({1: 19, 1_000: 1, 1_000_000: 1}) == 1
    assert decide({1: 105, 1_000: 0, 1_000_000: 0}) == 1
    assert decide({1: 2, 1_000: 0, 1_000_000: 0}) is None     # too little evidence
    assert decide({1: 5, 1_000: 1, 1_000_000: 0}) is None     # not 10x the runner-up
    assert decide({1: 40, 1_000: 2, 1_000_000: 0}) is None    # two conflicting matches
    assert decide({1: 0, 1_000: 0, 1_000_000: 35}) is None    # declared unit is right
    assert decide({1: 0, 1_000: 12, 1_000_000: 0}) == 1_000


def test_r169_data_file_shape():
    data = json.loads(rl._PROVED_UNIT_OVERRIDES_PATH.read_text(encoding="utf-8"))
    codes = {f"{s}_{b}" for s in ("BS", "IS", "CF", "SCE") for b in ("C", "S")}
    for rcept, secs in data.items():
        assert len(rcept) == 14 and rcept.isdigit(), rcept
        assert secs and set(secs) <= codes, (rcept, secs)
        assert set(secs.values()) <= {1, 1_000}, (rcept, secs)
