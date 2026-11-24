"""R383 - the legacy walker reads a bare `N. 재무제표 등` heading + period table + BS-looking table
as the separate balance sheet.

삼성생명 20140515001084 (2014 Q1): the separate statements start under the section heading
`2. 재무제표 등` (and a period table) with no `재무상태표` title; its IS/CF/SCE carry titles, so only the
separate BS was missing (issue #572334).
"""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl
import fin2.extract.text as tx

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
RC = "20140515001084"


def _extract():
    g = glob.glob(str(ROOT / "KOSPI" / "00126256_*" / "quarter" / "2014" / f"{RC}.xml"))
    if not g:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(Path(g[0]), rcept_no=RC, corp_code="00126256",
                                   report_fiscal_year=2014, report_fiscal_period="Q1")


def _sep_bs(lines):
    return {l.label_raw: l.value_won for l in lines
            if l.statement == "BS" and l.basis == "separate" and l.col_index == 0}


def test_switch_exists():
    assert tx._R383_LEGACY_FS_ETC_HEADING_BS is True


def test_samsung_life_separate_bs_is_read():
    bs = _sep_bs(_extract())
    assert bs["Ⅰ.현금및현금성자산"] == 1_439_443_000_000
    assert bs["부       채       총       계"] == 175_510_013_000_000


def test_switch_off_has_no_separate_bs_and_nothing_else_changes():
    on = _extract()
    tx._R383_LEGACY_FS_ETC_HEADING_BS = False
    try:
        off = _extract()
    finally:
        tx._R383_LEGACY_FS_ETC_HEADING_BS = True
    key = lambda l: (l.statement, l.basis, l.table_seq, l.col_index, l.label_raw, l.value_won)
    assert _sep_bs(off) == {}
    assert {key(l) for l in off} <= {key(l) for l in on}
    assert all(key(l)[:2] == ("BS", "separate") for l in on if key(l) not in {key(x) for x in off})


def test_totals_guard_reads_spaced_labels_and_rejects_other_tables():
    from lxml import etree

    def tbl(*labels):
        rows = "".join(f"<TR><TD>{l}</TD><TD>1</TD></TR>" for l in labels)
        return etree.fromstring(f"<TABLE>{rows}</TABLE>")
    assert tx._balance_sheet_by_compact_totals(tbl("자       산       총       계", "부 채 총 계"))
    assert not tx._balance_sheet_by_compact_totals(tbl("영업수익", "영업이익", "당기순이익"))
    assert not tx._balance_sheet_by_compact_totals(tbl("자산총계"))      # needs a liabilities/equity total too
