"""R382 - an SCE row whose label cell is blank but that prints amounts is kept with label ''.

하나금융지주 20141114001082 연결 SCE: the unlabeled subtotal row between `기타` and `연결당기순이익`
(1,215,249 | 299,121 | 6,814,903 | (80,949) | 277,944 | 5,547,887 | ...) was dropped.
키움증권 20140813000473 연결 SCE: the row under `해외사업환산손익` printing (12,397,652).
"""
import glob
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _extract(corp, sub, rcept, fy, period):
    g = glob.glob(str(ROOT / "KOSPI" / f"{corp}_*" / sub / f"{rcept}.xml"))
    if not g:
        pytest.skip("original XML is not on disk")
    return rl.extract_report_lines(Path(g[0]), rcept_no=rcept, corp_code=corp,
                                   report_fiscal_year=fy, report_fiscal_period=period)


def _blank_row(lines, basis="consolidated"):
    return {l.col_index: l.value_won for l in lines
            if l.statement == "SCE" and l.basis == basis and l.label_raw == ""}


def test_switch_exists():
    assert rl._R382_SCE_BLANK_LABEL_ROWS is True


def test_hana_unlabeled_subtotal_row_is_kept():
    lines = _extract("00547583", "quarter/2014", "20141114001082", 2014, "Q3")
    row = _blank_row(lines)
    assert row == {0: 1215249000000, 1: 299121000000, 2: 6814903000000, 3: -80949000000,
                   4: 277944000000, 5: 5547887000000, 6: 14074155000000, 7: 4546878000000,
                   8: 18621033000000}


def test_kiwoom_blank_row_under_foreign_translation_is_kept():
    lines = _extract("00296290", "half/2014", "20140813000473", 2014, "H1")
    assert _blank_row(lines) == {3: -12397652, 5: -12397652, 7: -12397652}


def test_switch_off_drops_them_and_nothing_else_changes():
    on = _extract("00296290", "half/2014", "20140813000473", 2014, "H1")
    rl._R382_SCE_BLANK_LABEL_ROWS = False
    try:
        off = _extract("00296290", "half/2014", "20140813000473", 2014, "H1")
    finally:
        rl._R382_SCE_BLANK_LABEL_ROWS = True
    key = lambda l: (l.statement, l.basis, l.table_seq, l.col_index, l.label_raw, l.value_won)
    assert _blank_row(off) == {}
    assert {key(l) for l in off} <= {key(l) for l in on}
    assert {key(l) for l in on} - {key(l) for l in off} == {key(l) for l in on if l.label_raw == "" and l.statement == "SCE"}
