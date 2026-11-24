"""R384 - a body-statement row whose label is printed in two cells (ordinal / blank, then name) is one label.

팬오션 20140515001895 별도 IS (web-view print): `II.` | `매출원가` | note 15 | (290,907) | | (1,120,270).
Before, the name cell was dropped as extra text, the label stayed `II.`, and the note cell 15 became an
amount (15,000,000). A printed dash in the first amount slot must keep its place (R384 dash guard).
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

import parser.xml.table_extractor as te
import fin2.extract.report_lines as rl

ROOT = Path(__file__).resolve().parents[1] / "raw_report"


def _tr(*cells):
    return "<TR>" + "".join(f"<TD>{c}</TD>" for c in cells) + "</TR>"


def _table(rows):
    head = "<THEAD><TR><TH COLSPAN=\"2\">과 목</TH><TH>주 석</TH><TH>당기</TH><TH>당기합계</TH><TH>전기</TH><TH>전기합계</TH></TR></THEAD>"
    return etree.fromstring("<TABLE>" + head + "<TBODY>" + "".join(rows) + "</TBODY></TABLE>")


def test_switch_exists():
    assert te._R384_SPLIT_LABEL_CELLS is True


def test_merge_ordinal_and_name():
    cells, els = te._merge_split_label_cells(["II.", "매출원가", "15", "(290,907)", "", "(1,120,270)", ""], list(range(7)))
    assert cells[0] == "II. 매출원가"
    assert cells[1:] == ["15", "(290,907)", "", "(1,120,270)", ""]
    assert els == [0, 2, 3, 4, 5, 6]


def test_merge_blank_first_cell_keeps_name_only():
    cells, _ = te._merge_split_label_cells(["", "보험수리적손익", "", "(21)", "", "(17)", ""], list(range(7)))
    assert cells[0] == "보험수리적손익"


def test_no_merge_when_second_cell_is_amount_or_note():
    for second in ("15", "(290,907)", "-", "", "1,234"):
        cells = ["II.", second, "x", "y"]
        assert te._merge_split_label_cells(cells, list(range(4)))[0] == cells


def test_no_merge_when_first_cell_is_a_name():
    cells = ["매출액", "영업수익", "1", "2"]
    assert te._merge_split_label_cells(cells, list(range(4)))[0] == cells


def test_extract_rows_reads_label_note_and_amounts():
    t = _table([
        _tr("I.", "매출액", "", "349,924", "", "1,060,241", ""),
        _tr("II.", "매출원가", "15", "(290,907)", "", "(1,120,270)", ""),
        _tr("XII.", "법인세비용(수익)", "18", "-", "", "(4,979)", ""),
    ])
    rows = te.extract_rows(t, multiplier=1, num_cols=3, direct_only=True, skip_junk=False)
    by = {r.account_name: r.amounts for r in rows}
    assert by["I. 매출액"][0] == 349924
    assert by["II. 매출원가"][:3] == [-290907, None, -1120270]   # note 15 is not an amount
    # the printed dash keeps the current-period slot; the prior value stays in the prior slot
    assert by["XII. 법인세비용(수익)"][0] is None and by["XII. 법인세비용(수익)"][2] == -4979


def test_pan_ocean_filing():
    g = glob.glob(str(ROOT / "KOSPI" / "00122737_*" / "quarter" / "2014" / "20140515001895.viewer.xml"))
    if not g:
        pytest.skip("web-view print is not on disk")
    lines = rl.extract_report_lines(Path(g[0]), rcept_no="20140515001895", corp_code="00122737",
                                    report_fiscal_year=2014, report_fiscal_period="Q1")
    is_s = [l for l in lines if l.statement == "IS" and l.basis == "separate"]
    cell = {(l.label_raw, l.col_index): l.value_won for l in is_s}
    assert cell[("II. 매출원가", 0)] == -290907000000
    assert cell[("II. 매출원가", 1)] == -1120270000000
    assert cell[("IV. 판매비", 0)] == -6969000000
    assert cell[("VII. 금융수익", 0)] == 963000000
    assert cell[("XII. 법인세비용(수익)", 1)] == -4979000000
    assert ("XII. 법인세비용(수익)", 0) not in cell
    assert not any(l.value_won in (15000000, 17000000, 18000000, 16000000) for l in is_s)
