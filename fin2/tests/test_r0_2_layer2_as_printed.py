"""R0-2 (2026-10-10) — layer 2 stores printed values; the old repair rules become layer-3 corrections.

LB인베스트먼트 2024 반기 `20240814002514` 연결 SCE '연차배당' is printed 4,599,088,600 without
parentheses in 이익잉여금 and 지배기업 합계; R162 restores the minus from the column roll-forward.
After R0-2 the default extraction keeps the printed sign and the restored value is a correction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fin2.extract import as_printed as AP  # noqa: E402
from fin2.extract.layer3_corrections import extract_xml_with_corrections  # noqa: E402
from fin2.extract.report_lines import extract_report_lines  # noqa: E402

_LB = ROOT / "raw_report/KOSDAQ/00231901_LB인베스트먼트/half/2024/20240814002514.xml"
_RC = "20240814002514"
_KW = dict(rcept_no=_RC, corp_code="00231901", report_fiscal_year=2024, report_fiscal_period="H1")


def _dividend_cells(lines):
    return {l.col_index: l.value_won for l in lines
            if l.statement == "SCE" and l.basis == "consolidated" and l.table_seq == 0
            and l.row_order == 9 and l.col_index in (4, 5)}


@pytest.fixture
def lb_path():
    if not _LB.exists():
        pytest.skip("raw_report not mounted")
    return _LB


def test_default_extraction_keeps_the_printed_sign(lb_path, monkeypatch):
    monkeypatch.delenv(AP.ENV, raising=False)
    lines = extract_report_lines(str(lb_path), include_notes=False, **_KW)
    assert _dividend_cells(lines) == {4: 4_599_088_600, 5: 4_599_088_600}


def test_legacy_switch_still_restores(lb_path, monkeypatch):
    monkeypatch.setenv(AP.ENV, "0")
    lines = extract_report_lines(str(lb_path), include_notes=False, **_KW)
    assert _dividend_cells(lines) == {4: -4_599_088_600, 5: -4_599_088_600}


def test_restored_sign_becomes_a_layer3_correction(lb_path, monkeypatch):
    monkeypatch.delenv(AP.ENV, raising=False)
    lines, corrections = extract_xml_with_corrections(str(lb_path), include_notes=False, **_KW)
    assert _dividend_cells(lines) == {4: 4_599_088_600, 5: 4_599_088_600}
    hit = {c["col_index"]: c for c in corrections
           if c["statement"] == "SCE" and c["basis"] == "consolidated" and c["table_seq"] == 0
           and c["row_order"] == 9 and c["col_index"] in (4, 5)}
    assert set(hit) == {4, 5}
    for c in hit.values():
        assert (c["printed_value"], c["corrected_value"]) == (4_599_088_600, -4_599_088_600)
        assert c["kind"] == "value" and c["rule"] == "R162_sign_loss"
    # every correction is a real difference and names its rule
    assert all(c["printed_value"] != c["corrected_value"] and c["rule"] for c in corrections)


_JEJU = ROOT / "raw_report/KOSPI/00148832_제주은행/quarter/2015/20150515002022.xml"


def test_typo_fixed_cell_is_a_value_correction_on_the_printed_null_row(monkeypatch):
    # 제주은행 2015 1분기 연결 BS 'Ⅰ. 지배기업 소유지분' is printed `310.731` (백만원). R159 lists it as
    # 310,731. Since R160 (2026-10-12) the printed reading keeps the row with a NULL value and the
    # printed text in value_raw, so the R159 fix is a 'value' correction on that row (before: no
    # layer-2 row and a 'fill'). report_lines_l3 shows the same 310,731,000,000 either way.
    if not _JEJU.exists():
        pytest.skip("raw_report not mounted")
    monkeypatch.delenv(AP.ENV, raising=False)
    lines, corrections = extract_xml_with_corrections(
        str(_JEJU), rcept_no="20150515002022", corp_code="00148832", report_fiscal_year=2015,
        report_fiscal_period="Q1", include_notes=False)
    row = [l for l in lines if l.statement == "BS" and l.basis == "consolidated"
           and l.table_seq == 0 and l.row_order == 21 and l.col_index == 0]
    assert [(l.value_won, l.value_raw) for l in row] == [(None, "310.731")]
    fix = [c for c in corrections if c["statement"] == "BS" and c["row_order"] == 21]
    assert len(fix) == 1 and fix[0]["kind"] == "value" and fix[0]["rule"] == "R159_typo"
    assert (fix[0]["printed_value"], fix[0]["corrected_value"]) == (None, 310_731_000_000)
