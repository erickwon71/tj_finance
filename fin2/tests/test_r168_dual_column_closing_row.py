"""R168(2026-09-24) regression test — group-closing rows of the old two-column
print layout ([detail cell, balance cell] per period) were dropped.

Most rows fill one cell; a group-closing row (대손충당금 · 감가상각누계액 ·
전환권조정 · 평가충당금 · 국고보조금) fills BOTH. `select_by_header_columns()`
saw two different real values in a subtype-free merge group and skipped the
rank (R6), so the row vanished. R155 recorded this as "won't fix" on a breadth
scan (1 filing in 2,528 companies); the verification campaign then found 16
크래프톤 filings with 94 lost rows (issues #59~#102).

## Design: the row proves itself, R6 stays

The left cell is taken ONLY when the detail-cell run since the last balance row
reproduces the balance cell exactly:

    단기대여금      5,917,135,510
    대손충당금        402,125,052   5,515,010,458   5,917,135,510 - 402,125,052
    기계장치        6,264,756,463
    감가상각누계액  3,327,312,560
    국고보조금          3,338,881   2,934,105,022   deduction chain (티로보틱스)

Two different values WITHOUT that proof are still skipped — R6 is unchanged
for every other caller (insurance/securities detail/subtotal layouts, R125).

Run: pytest fin2/tests/test_r168_dual_column_closing_row.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xml.table_extractor import (  # noqa: E402
    HeaderColumn, select_by_header_columns, update_dual_closing_runs,
)

_COLS = [HeaderColumn(position=0, period_key="제3기", period_rank=0),
         HeaderColumn(position=1, period_key="제3기", period_rank=0),
         HeaderColumn(position=2, period_key="제2기", period_rank=1),
         HeaderColumn(position=3, period_key="제2기", period_rank=1)]


def _run(rows):
    """Feed rows through the selector exactly as `report_lines` does."""
    runs: dict[int, list] = {}
    out = []
    for amounts in rows:
        out.append(select_by_header_columns(_COLS, amounts, closing_runs=runs))
        update_dual_closing_runs(_COLS, amounts, runs)
    return out


def test_krafton_allowance_row_recovered():
    # 크래프톤 20171114001378 [별도] BS
    picked = _run([
        [None, 23_995_255_797, None, None],          # (1)당좌자산
        [5_917_135_510, None, None, None],           # 단기대여금
        [402_125_052, 5_515_010_458, None, None],    # 대손충당금
    ])
    assert picked[2] == {0: 402_125_052}


def test_tirobotics_deduction_chain_recovered():
    # 티로보틱스 20180402000209 [별도] BS: gross, contra (left only), contra (both)
    picked = _run([
        [6_264_756_463, None, None, None],           # 기계장치
        [3_327_312_560, None, None, None],           # 감가상각누계액
        [3_338_881, 2_934_105_022, None, None],      # 국고보조금
    ])
    assert picked[1] == {0: 3_327_312_560}
    assert picked[2] == {0: 3_338_881}


def test_parenthesised_contra_signed_sum_recovered():
    picked = _run([
        [1_000, None, None, None],
        [-300, 700, None, None],                     # (300) | 700
    ])
    assert picked[1] == {0: -300}


def test_unproved_pair_still_skipped_r6():
    picked = _run([
        [1_000, None, None, None],
        [300, 999, None, None],                      # 1,000 - 300 != 999
    ])
    assert picked[1] == {}


def test_no_run_still_skipped_r6():
    # Balance row immediately before: there is no open group to close.
    picked = _run([
        [None, 5_000, None, None],
        [300, 4_700, None, None],
    ])
    assert picked[1] == {}


def test_balance_row_ends_the_group():
    picked = _run([
        [1_000, None, None, None],
        [None, 1_000, None, None],                   # balance row closes the group
        [300, 700, None, None],                      # no run left -> not proved
    ])
    assert picked[2] == {}


def test_without_closing_runs_behaviour_unchanged():
    # Existing callers that do not pass `closing_runs` keep R6 exactly.
    assert select_by_header_columns(_COLS, [402, 5_515, None, None]) == {}


def test_prior_period_rank_tracked_independently():
    picked = _run([
        [1_000, None, 900, None],
        [100, 900, 50, 850],
    ])
    assert picked[1] == {0: 100, 1: 50}


def test_subtype_group_not_touched():
    cols = [HeaderColumn(position=0, period_key="제3기", period_rank=0, subtype="three_month"),
            HeaderColumn(position=1, period_key="제3기", period_rank=0, subtype="cumulative")]
    runs: dict[int, list] = {}
    update_dual_closing_runs(cols, [1_000, None], runs)
    assert runs == {}
    assert select_by_header_columns(cols, [300, 700], closing_runs={0: [1_000]}) == {0: 700}


_KRAFTON = Path(__file__).resolve().parents[2] / (
    "raw_report/KOSPI/00760971_크래프톤/quarter/2017/20171114001378.xml")


@pytest.mark.skipif(not _KRAFTON.exists(), reason="raw_report not mounted")
def test_krafton_real_filing_rows_emitted():
    from fin2.extract.report_lines import extract_report_lines

    lines = extract_report_lines(str(_KRAFTON), corp_code="00760971",
                                 rcept_no="20171114001378",
                                 report_fiscal_year=2017, report_fiscal_period="Q3")
    sep_bs = {(ln.label_raw.strip(), ln.value_won) for ln in lines
              if ln.basis == "separate" and ln.statement == "BS" and ln.col_index == 0}
    for label, amount in [("대손충당금", 402_125_052), ("대손충당금", 7_060_228_324),
                          ("감가상각누계액", 2_119_022_073), ("감가상각누계액", 806_284_027),
                          ("유동성전환권조정", 867_774_588)]:
        assert any(lab == label and a == amount for lab, a in sep_bs), (label, amount)
