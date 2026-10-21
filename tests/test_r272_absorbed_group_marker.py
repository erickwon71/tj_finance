"""R272 — `…와 그 종속기업의 … 연결재무제표` marks another entity, scoped to its own basis."""
from pathlib import Path

import pytest
from lxml import etree

from fin2.extract.other_entity_tables import drop_other_entity_tables

RAW = Path("/Volumes/dart_data/raw_report/KOSPI/00896285_삼양사/annual/2015/20160330003169.xml")

SENTENCE = "<P>2016년 1월 1일을 합병기일로 삼양사에 흡수합병된 삼양제넥스와 그 종속기업의 최근 3년간 연결재무제표입니다.</P>"


def _run():
    root = etree.fromstring(
        "<BODY>" + "<TABLE><TR><TD>filer C</TD></TR></TABLE>" + SENTENCE
        + "<TABLE><TR><TD>absorbed C</TD></TR></TABLE>"
        + "<TABLE><TR><TD>filer S</TD></TR></TABLE></BODY>")
    t = root.findall(".//TABLE")
    groups = {"BS_C": [(t[0], None, "C"), (t[1], None, "C")], "BS_S": [(t[2], None, "S")]}
    return drop_other_entity_tables(root, groups)


def test_group_sentence_drops_absorbed_consolidated_table_only():
    out, dropped = _run()
    assert len(out["BS_C"]) == 1
    assert len(out["BS_S"]) == 1
    assert dropped == [("BS_C", "", "삼양제넥스")]


def test_switch_off_keeps_old_behaviour(monkeypatch):
    import fin2.extract.other_entity_tables as o
    monkeypatch.setattr(o, "_R272_ABSORBED_WITH_SUBSIDIARIES", False)
    out, dropped = _run()
    assert dropped == [] and len(out["BS_C"]) == 2


@pytest.mark.skipif(not RAW.exists(), reason="raw report not mounted")
def test_samyang_consolidated_has_only_filer_table():
    from fin2.extract.report_lines import extract_report_lines
    rows = extract_report_lines(str(RAW), rcept_no="20160330003169", corp_code="00896285",
                                report_fiscal_year=2015, report_fiscal_period="FY", include_notes=True)
    seqs = {r.table_seq for r in rows if r.statement in ("BS", "IS", "CF", "SCE") and r.basis == "consolidated"}
    assert seqs == {0}
