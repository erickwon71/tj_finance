"""R239 — bare `계속영업` / `중단영업` / `계속영업과 중단영업` rows printed under a 기본/희석 주당이익
header were read with the IS table's unit (백만원), so EPS 7,257 won became 7,257,000,000.

Found by the verification campaign (LS 20171114001452 and 13 sibling filings, 2015-2017).
Earlier rules: R145 (EPS structural label), R147 (`E`: child must declare 원 itself). These rows
declare nothing and carry no `주당`, so neither rule saw them.

Claims:
  1. under a 기본/희석 주당이익 section the three bare labels are EPS.
  2. the same labels outside an EPS section (body totals) stay body rows.
  3. labels that are not a continuing/discontinued row stay non-EPS (e.g. share counts).
  4. nothing changes before FY2015.
  5. end to end: a 백만원 table keeps the EPS child in won.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import _emit_section_lines, _is_eps_label  # noqa: E402

_PATH = "주당이익>기본 및 희석주당이익"


def _run(xml: str, *, unit: int):
    out: list = []
    _emit_section_lines(
        "IS_C", [(etree.fromstring(xml), unit, None)], emit=out.append,
        corp_code="TESTCORP", rcept_no="R239-0000000001",
        report_fiscal_year=2017, report_fiscal_period="Q3",
        doc_default_unit=(None, None), section_unit_cache={})
    return out


def test_bare_continuing_labels_under_diluted_header_are_eps():
    for label in ("계속영업과 중단영업", "계속영업", "중단영업", "1. 계속영업", "계속사업"):
        assert _is_eps_label(label, section_path=_PATH, report_fiscal_year=2017), label


def test_same_labels_outside_eps_section_are_not_eps():
    for path in (None, "당기순이익의 귀속", "법인세비용차감전계속영업이익"):
        assert not _is_eps_label("계속영업", section_path=path, report_fiscal_year=2017), path


def test_other_children_of_the_eps_section_are_not_rescued():
    for label in ("가중평균유통보통주식수", "보통주", "계속영업이익(손실) 총액"):
        assert not _is_eps_label(label, section_path=_PATH, report_fiscal_year=2017), label


def test_header_without_method_word_is_not_enough():
    assert not _is_eps_label("계속영업", section_path="주당이익", report_fiscal_year=2017)


def test_no_effect_before_2015():
    assert not _is_eps_label("계속영업", section_path=_PATH, report_fiscal_year=2014)


def test_share_class_row_under_won_declared_eps_title_is_eps():
    path = "XV. 주당이익(단위:원)"
    assert _is_eps_label("1. 보통주", section_path=path, report_fiscal_year=2015)
    assert _is_eps_label("우선주", section_path=path, report_fiscal_year=2015)


def test_share_class_row_elsewhere_is_not_eps():
    # a share-count table, an EPS title without a won declaration, and a body table
    assert not _is_eps_label("보통주", section_path="주당이익(단위:주)", report_fiscal_year=2015)
    assert not _is_eps_label("보통주", section_path="주당이익", report_fiscal_year=2015)
    assert not _is_eps_label("보통주", section_path=None, report_fiscal_year=2015)


_LS_TABLE = """<TABLE>
<TR><TD>비지배지분</TD><TD>23,902</TD></TR>
<TR><TD>주당이익</TD><TD></TD></TR>
<TR><TD>　기본 및 희석주당이익</TD><TD></TD></TR>
<TR><TD>　　계속영업과 중단영업</TD><TD>7,257</TD></TR>
<TR><TD>　　계속영업</TD><TD>6,147</TD></TR>
</TABLE>"""


def test_million_table_keeps_eps_child_in_won():
    rows = _run(_LS_TABLE, unit=1_000_000)
    by_label = {l.label_raw.strip(): l.value_won for l in rows
                if l.label_raw.strip() in ("계속영업과 중단영업", "계속영업")}
    assert by_label == {"계속영업과 중단영업": 7257, "계속영업": 6147}
    keys = [(l.label_raw.strip(), l.section_path, l.col_index) for l in rows]
    assert len(keys) == len(set(keys)), keys
    # the body row of the same table keeps the table unit
    body = {l.label_raw.strip(): l.value_won for l in rows if l.label_raw.strip() == "비지배지분"}
    assert body == {"비지배지분": 23_902_000_000}
