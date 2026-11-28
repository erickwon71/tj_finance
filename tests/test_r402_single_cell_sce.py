"""R402 - a statement of changes in equity printed as ONE row with ONE newline-joined cell.

Haitai Confectionery 20141201000889 / 20140829002018: the separate SCE table is a single TD whose lines are
`과 목`, six column names, then `label / six values` records (blank lines between records). The walker saw no
data rows and dropped the table (missing_row #573126 #573127). The cell is rebuilt as an ordinary TR/TD table
and read by the normal SCE emitter; nothing is added, moved or corrected (R0-2).
"""
import glob
from pathlib import Path

import pytest
from lxml import etree

import fin2.extract.report_lines as rl
from fin2.extract.text import expand_single_cell_sce_table

ROOT = Path(__file__).resolve().parents[1] / "raw_report"
SD = Path("/Volumes/dart_data/raw_report")


def _blob(lines):
    tbl = etree.fromstring("<TABLE><TBODY><TR><TD/></TR></TBODY></TABLE>")
    tbl.find(".//TD").text = "\n".join(lines)
    return tbl


HEAD = ["과     목", "자본금", "자본잉여금", "총   계"]
PAD = ["", "", ""]


def _rows(tbl):
    return [[td.text for td in tr] for tr in tbl.iter("TR")]


def test_expands_label_value_records_as_printed():
    lines = (HEAD + PAD + ["2013년 1월 1일(당기초)", "10,207 ", "(18,113)", "154,980 "] + PAD
             + ["총포괄손익:"] + PAD + ["분기순이익", "-", "13,898", "13,898 "] + PAD
             + ["자본잉여금의 이입", "　", "-", "　"] + PAD + ["x"] * 20)
    lines = lines[:-20]
    lines += ["2014년 9월 30일(당분기말)", "1", "2", "3"] + [""] * 20
    got = _rows(expand_single_cell_sce_table(_blob(lines)))
    assert got[0] == ["과     목", "자본금", "자본잉여금", "총   계"]
    assert got[1] == ["2013년 1월 1일(당기초)", "10,207 ", "(18,113)", "154,980 "]
    assert got[2] == ["총포괄손익:"]
    assert got[3] == ["분기순이익", "-", "13,898", "13,898 "]
    assert got[4] == ["자본잉여금의 이입", "　", "-", "　"]          # full-width blanks stay as printed


def test_refuses_short_value_run():
    lines = (HEAD + PAD + ["2013년 1월 1일(당기초)", "10,207 ", "(18,113)", "154,980 "] + PAD
             + ["분기순이익", "-", "13,898"] + PAD + [""] * 20)        # 2 values instead of 3
    assert expand_single_cell_sce_table(_blob(lines)) is None


def test_refuses_other_shapes():
    assert expand_single_cell_sce_table(_blob(["재무상태표"] + [""] * 30)) is None      # not '과 목'
    tbl = etree.fromstring("<TABLE><TBODY><TR><TD>a</TD><TD>b</TD></TR></TBODY></TABLE>")
    assert expand_single_cell_sce_table(tbl) is None                                   # more than one cell


def _source(path_glob, rcept):
    for base in (ROOT, SD):
        g = glob.glob(str(base / path_glob / f"{rcept}.xml"))
        if g:
            return Path(g[0])
    pytest.skip("source XML is not on disk")


@pytest.mark.parametrize("path_glob,rcept,fp", [
    ("KOSPI/00428321_*/quarter/2014", "20141201000889", "Q3"),
    ("KOSPI/00428321_*/half/2014", "20140829002018", "H1"),
])
def test_haitai_separate_sce_is_read(path_glob, rcept, fp):
    lines = rl.extract_report_lines(_source(path_glob, rcept), rcept_no=rcept, corp_code="00428321",
                                    report_fiscal_year=2014, report_fiscal_period=fp)
    sce = [l for l in lines if l.statement == "SCE" and l.basis == "separate"]
    assert sce
    first = [l for l in sce if l.row_order == 0 and l.col_index == 0]
    assert first and first[0].value_won == 10207277000          # printed 10,207,277,000 (2013년 1월 1일 자본금)
