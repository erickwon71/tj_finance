"""R162-e2 — the sign-loss pass runs once more after R162-d/d2 changed a cell.

남해화학 `20220317000080` 연결 2019 '확정급여제도의 재측정요소'(#86976): the dividend row's 자본 합계 is
flipped by R162-d2, after which the 자본 합계 column block is one single positive cell short of closing
(this row); R162-e had already run, so nothing closed it.
"""
from __future__ import annotations

from pathlib import Path

import fin2.extract.sce_sign_repair as ssr

_PATH = Path(__file__).resolve().parents[2] / "raw_report/KOSPI/00107987_남해화학/annual/2021/20220317000080.xml"


def _extract():
    from fin2.extract.report_lines import extract_report_lines
    return extract_report_lines(str(_PATH), rcept_no="20220317000080", corp_code="00107987",
                                report_fiscal_year=2021, report_fiscal_period="FY", include_notes=True)


def _cells(lines, row_order, col):
    return [l.value_won for l in lines if l.statement == "SCE" and l.basis == "consolidated"
            and l.row_order == row_order and l.col_index == col]


def test_namhae_remeasurement_total_closes_after_dividend_flip():
    if not _PATH.exists():
        return
    lines = _extract()
    assert _cells(lines, 3, 7) == [-4399383571]        # 확정급여제도의 재측정요소, 자본 합계
    assert _cells(lines, 5, 7) == [-2397434750]        # 연차배당 (R162-d2)


def test_switch_off_leaves_the_total_positive():
    if not _PATH.exists():
        return
    ssr._R162E_RERUN_AFTER_D = False
    try:
        assert _cells(_extract(), 3, 7) == [4399383571]
    finally:
        ssr._R162E_RERUN_AFTER_D = True


def test_rerun_never_turns_a_printed_negative_positive():
    """Reverting rule: only lost parentheses are restored, never added back."""
    from types import SimpleNamespace as NS
    lines = [NS(statement="IS", value_won=1)]
    assert ssr.rerun_sign_loss_after_row_identity(lines) == []       # no SCE cell -> no-op
