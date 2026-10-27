"""R285 regression: a row whose every amount cell prints a won suffix is loaded with adecimal=0.

Run: pytest fin2/tests/test_r285_won_suffix_row_adecimal.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import _row_prints_won, extract_report_lines  # noqa: E402

_HEUNGKUK_2018H1 = Path("/Volumes/dart_data/raw_report/KOSPI/00103176_흥국화재/half/2018/20180814002698.xml")


def _row(*cells):
    return SimpleNamespace(raw_amounts=list(cells))


def test_all_won_suffix_cells_make_a_won_row():
    assert _row_prints_won(_row("243원", "188원", "721원", "869원"))
    assert _row_prints_won(_row("(89원)", "-"))
    assert _row_prints_won(_row("(2,564)원"))
    assert _row_prints_won(_row("2,552 원"))


def test_mixed_or_plain_cells_keep_the_table_unit():
    assert not _row_prints_won(_row("1,234", "188원"))
    assert not _row_prints_won(_row("1,234", "5,678"))
    assert not _row_prints_won(_row("", "-"))
    assert not _row_prints_won(_row("1,234천원"))


def test_heungkuk_2018h1_eps_children_are_won_and_values_unchanged():
    if not _HEUNGKUK_2018H1.exists():
        return
    lines = extract_report_lines(
        _HEUNGKUK_2018H1, rcept_no="20180814002698", corp_code="00103176",
        report_fiscal_year=2018, report_fiscal_period="H1", include_notes=False)
    eps = [l for l in lines if l.statement == "IS" and "주당" in (l.section_path or "")]
    assert all(l.adecimal == 0 for l in eps)
    assert sorted(l.value_won for l in eps) == [187, 188, 237, 238, 867, 869, 892, 894]
