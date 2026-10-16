"""R245 — a later body table that follows a marker naming another legal entity is not the filer's."""
from pathlib import Path

import pytest
from lxml import etree

from fin2.extract.other_entity_tables import drop_other_entity_tables, normalize_entity

RAW = Path(__file__).resolve().parents[1] / "raw_report"


def _doc(*parts):
    return etree.fromstring("<BODY>" + "".join(parts) + "</BODY>")


def _groups(root):
    tables = root.findall(".//TABLE")
    return {"BS_S": [(t, None, "SEP") for t in tables]}


def _kept(root):
    out, dropped = drop_other_entity_tables(root, _groups(root))
    return len(out.get("BS_S", [])), dropped


def test_unmarked_first_table_then_named_other_entity_is_dropped():
    root = _doc("<TABLE><TR><TD>filer</TD></TR></TABLE>",
                "<P>2016년 1월 1일을 합병기일로 삼양사에 흡수합병된 삼양제넥스의 최근 3년간 재무제표입니다.</P>",
                "<TABLE><TR><TD>absorbed</TD></TR></TABLE>")
    n, dropped = _kept(root)
    assert n == 1 and dropped == [("BS_S", "", "삼양제넥스")]


def test_bracket_markers_keep_first_entity_and_drop_the_second():
    root = _doc("<P><SPAN>[합병법인 한화엠지아이기업인수목적]</SPAN></P>",
                "<TABLE><TR><TD>spac</TD></TR></TABLE>",
                "<P><SPAN>[피합병법인 우정비에스씨]</SPAN></P>",
                "<TABLE><TR><TD>target</TD></TR></TABLE>")
    n, dropped = _kept(root)
    assert n == 1 and dropped[0][1:] == ("한화엠지아이기업인수목적", "우정비에스씨")


def test_same_entity_named_twice_is_kept():
    root = _doc("<P>[주식회사 케이피에스]</P>", "<TABLE><TR><TD>a</TD></TR></TABLE>",
                "<P>[(주)케이피에스]</P>", "<TABLE><TR><TD>b</TD></TR></TABLE>")
    n, dropped = _kept(root)
    assert n == 2 and dropped == []


def test_no_markers_keeps_everything():
    root = _doc("<TABLE><TR><TD>a</TD></TR></TABLE>", "<TABLE><TR><TD>b</TD></TR></TABLE>")
    assert _kept(root) == (2, [])


def test_bracket_account_names_are_not_markers():
    root = _doc("<P>[기타자본항목]</P>", "<TABLE><TR><TD>a</TD></TR></TABLE>",
                "<P>[이익잉여금]</P>", "<TABLE><TR><TD>b</TD></TR></TABLE>")
    assert _kept(root) == (2, [])


def test_normalize_entity():
    assert normalize_entity("주식회사 밸로프") == normalize_entity("(주)밸로프") == "밸로프"


@pytest.mark.parametrize("rel,gone", [
    ("KOSPI/00896285_삼양사/annual/2015/20160330003169.xml", {"BS_S": 1}),
    ("KOSDAQ/01398151_밸로프/quarter/2022/20221114002664.xml", {"BS_S": 1}),
    ("KOSDAQ/01326224_원바이오젠/annual/2020/20210315000269.xml", {"BS_S": 1}),
    ("KOSDAQ/01065013_콜마바이오텍/quarter/2017/20170529000084.viewer.xml", {"BS_S": 1}),
])
def test_real_merger_reports_keep_one_separate_bs_table(rel, gone):
    path = RAW / rel
    if not path.exists():
        pytest.skip("raw report not available")
    from fin2.extract.report_lines import _detect_body_statement_tables, _parse_xml_file
    from fin2.extract.text import _detect_fin_type
    root = _parse_xml_file(path)
    groups = _detect_body_statement_tables(root, _detect_fin_type(root, file_path=path), include_sce=True)
    out, _ = drop_other_entity_tables(root, groups)
    for code, n in gone.items():
        assert len(groups[code]) - len(out[code]) == n
    assert len(out["BS_S"]) == 1


def test_company_name_line_in_notes_is_not_a_marker():
    root = _doc("<TABLE><TR><TD>a</TD></TR></TABLE>", "<P>회사명 : 주식회사 젬백스링크(구, 주식회사 필링크)와 그 종속회사</P>",
                "<TABLE><TR><TD>b</TD></TR></TABLE>")
    assert _kept(root) == (2, [])
