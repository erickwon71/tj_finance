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


def test_typo_fixed_cell_the_printed_reading_drops_is_a_fill_with_its_row(monkeypatch):
    # 제주은행 2015 1분기 연결 BS 'Ⅰ. 지배기업 소유지분' is printed `310.731` (백만원). R159 lists it as
    # 310,731; the printed reading cannot parse it, so layer 2 has no row and layer 3 gets a 'fill'
    # carrying the whole row (report_lines_l3 adds it back).
    if not _JEJU.exists():
        pytest.skip("raw_report not mounted")
    monkeypatch.delenv(AP.ENV, raising=False)
    lines, corrections = extract_xml_with_corrections(
        str(_JEJU), rcept_no="20150515002022", corp_code="00148832", report_fiscal_year=2015,
        report_fiscal_period="Q1", include_notes=False)
    assert not [l for l in lines if l.statement == "BS" and l.basis == "consolidated"
                and l.table_seq == 0 and l.row_order == 21 and l.value_won is not None]
    fill = [c for c in corrections if c["statement"] == "BS" and c["row_order"] == 21]
    assert len(fill) == 1 and fill[0]["kind"] == "fill" and fill[0]["rule"] == "R159_typo"
    assert fill[0]["corrected_value"] == 310_731_000_000
    assert '"label_raw": "Ⅰ. 지배기업 소유지분"' in fill[0]["row_data"]
