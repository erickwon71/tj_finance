"""R244 — a label cell whose COLSPAN covers the label + note columns must not shift the amounts.

비나텍 20200330004723 separate IS: the row `당기손익으로재분류되지않는항목` prints one label cell with
COLSPAN=2 and then the current and prior amounts, so the row has one physical cell fewer than the
other rows and the current amount fell into the note slot (prior was stored as current).
"""
from lxml import etree

from parser.xml.table_extractor import extract_rows


def _table(rows):
    body = "".join(f"<TR>{r}</TR>" for r in rows)
    return etree.fromstring(
        "<TABLE><THEAD><TR><TH>과목</TH><TH>주석</TH><TH>제 2 기</TH><TH>제 1 기</TH></TR></THEAD>"
        f"<TBODY>{body}</TBODY></TABLE>")


NORMAL = "<TD>순확정급여부채의재측정요소</TD><TD>20</TD><TD>(208,918,143)</TD><TD>(559,363,860)</TD>"


def _amounts(rows):
    return {r.account_name.strip(): list(r.amounts) for r in extract_rows(_table(rows), num_cols=3, direct_only=False, skip_junk=False)}


def test_colspan_label_row_keeps_current_and_prior():
    wide = '<TD COLSPAN="2">당기손익으로재분류되지않는항목</TD><TD>(208,918,143)</TD><TD>(559,363,860)</TD>'
    got = _amounts([wide, NORMAL])
    assert got["당기손익으로재분류되지않는항목"][:2] == [-208918143, -559363860]
    assert got["순확정급여부채의재측정요소"][:2] == [-208918143, -559363860]


def test_colspan_label_row_that_prints_its_own_note_is_left_alone():
    wide = '<TD COLSPAN="2">당기손익으로재분류되지않는항목</TD><TD>19</TD><TD>(208,918,143)</TD><TD>(559,363,860)</TD>'
    got = _amounts([wide, NORMAL])
    assert got["당기손익으로재분류되지않는항목"][:2] == [-208918143, -559363860]
