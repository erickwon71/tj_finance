"""mn31 (B-3, R375): the machine raises no missing-cell finding for (a) a cell of a blank-first-cell source row
(the loader drops it by design, user decision 2026-11-06 kept as a limit 2026-11-21) and (b) an amount whose
label and value are both printed in another table of the same basis."""
from collections import Counter
from types import SimpleNamespace

from fin2.verification import machine_note as mn


def _src(amounts, basis="separate"):
    s = mn.SrcTable(idx=0, basis=basis)
    s.amounts = list(amounts)
    s.alt_amounts = list(amounts)
    s.values = tuple(a[0] for a in amounts)
    s.alt_values = s.values
    s.valueset = Counter(s.values)
    s.labels = frozenset(a[1] for a in amounts if a[1])
    return s


def _rows(table_seq, items, basis="separate"):
    return [SimpleNamespace(basis=basis, table_seq=table_seq, row_order=i, col_index=0, label_raw=lab,
                            col_label="", value_won=v, adecimal=0, value_raw=None)
            for i, (lab, v) in enumerate(items)]


def _compare(db_rows, src_tables):
    return mn.compare(mn.tables_from_rows(db_rows), src_tables, True)


def test_cell_of_a_blank_first_cell_row_is_no_missing_cell():
    src = _src([(5000000, "매출채권", 0, False), (13200, "미수금", 4, True), (7000000, "대여금", 0, False)])
    res = _compare(_rows(1, [("매출채권", 5000000), ("대여금", 7000000)]), [src])
    assert not [f for f in res.findings if f.get("kind") == "missing_cell"]


def test_same_missing_cell_of_a_row_with_its_own_label_is_still_reported():
    src = _src([(5000000, "매출채권", 0, False), (13200, "미수금", 4, False), (7000000, "대여금", 0, False)])
    res = _compare(_rows(1, [("매출채권", 5000000), ("대여금", 7000000)]), [src])
    assert [f["src"] for f in res.findings if f.get("kind") == "missing_cell"] == [13200]


def test_blank_row_limit_can_be_switched_off():
    src = _src([(5000000, "매출채권", 0, False), (13200, "미수금", 4, True), (7000000, "대여금", 0, False)])
    mn._MN31_BLANK_LABEL_LIMIT = False
    try:
        res = _compare(_rows(1, [("매출채권", 5000000), ("대여금", 7000000)]), [src])
    finally:
        mn._MN31_BLANK_LABEL_LIMIT = True
    assert [f["src"] for f in res.findings if f.get("kind") == "missing_cell"] == [13200]


def test_amount_with_the_same_label_in_another_table_is_no_missing_cell():
    src = _src([(5000000, "매출채권", 0, False), (13200, "미수금", 1, False), (7000000, "대여금", 0, False)])
    db = _rows(1, [("매출채권", 5000000), ("대여금", 7000000)]) + _rows(2, [("미수금", 13200), ("기타", 99000)])
    res = _compare(db, [src, _src([(13200, "미수금", 1, False), (99000, "기타", 1, False)])])
    assert not [f for f in res.findings if f.get("kind") == "missing_cell" and f.get("src") == 13200]


def test_same_amount_under_another_label_elsewhere_is_still_missing():
    src = _src([(5000000, "매출채권", 0, False), (13200, "미수금", 1, False), (7000000, "대여금", 0, False)])
    db = _rows(1, [("매출채권", 5000000), ("대여금", 7000000)]) + _rows(2, [("선수금", 13200), ("기타", 99000)])
    res = _compare(db, [src, _src([(13200, "선수금", 1, False), (99000, "기타", 1, False)])])
    assert 13200 in [f["src"] for f in res.findings if f.get("kind") == "missing_cell"]


def test_generic_total_label_is_never_a_pairing_proof():
    src = _src([(5000000, "매출채권", 0, False), (13200, "합계", 1, False), (7000000, "대여금", 0, False)])
    db = _rows(1, [("매출채권", 5000000), ("대여금", 7000000)]) + _rows(2, [("합계", 13200), ("기타", 99000)])
    res = _compare(db, [src, _src([(13200, "합계", 1, False), (99000, "기타", 1, False)])])
    assert 13200 in [f["src"] for f in res.findings if f.get("kind") == "missing_cell"]


def test_pairing_proof_must_come_from_another_table_not_the_compared_one():
    src = _src([(5000000, "재고자산", 0, False), (5000000, "재고자산", 1, False), (7000000, "대여금", 0, False)])
    res = _compare(_rows(1, [("재고자산", 5000000), ("대여금", 7000000)]), [src])
    assert [f["src"] for f in res.findings if f.get("kind") == "missing_cell"] == [5000000]


_XML = """<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>5. 재무제표 주석</TITLE>
<TABLE><THEAD><TR><TH>구분</TH><TH>금액</TH></TR></THEAD><TBODY>
<TR><TD ROWSPAN="2">대여금</TD><TD>5,000,000</TD></TR>
<TR><TD>6,000,000</TD></TR>
<TR><TD></TD><TD>7,000,000</TD></TR>
</TBODY></TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def test_rowspan_continuation_row_is_no_blank_label_row(tmp_path):
    p = tmp_path / "rs.xml"
    p.write_text(_XML, encoding="utf-8")
    tables, found = mn.load_source_tables(str(p))
    assert found
    flags = {a[0]: a[3] for a in tables[0].amounts}
    assert flags[6000000] is False          # its label cell is inherited from the row above (R166 loads it)
    assert flags[7000000] is True           # a truly blank label cell: the limit applies


def _flags(tmp_path, body, head="<TR><TH>구분</TH><TH>금액</TH></TR>"):
    xml = ("<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE><SECTION-2><TITLE>5. 재무제표 주석</TITLE>"
           f"<TABLE><THEAD>{head}</THEAD><TBODY>{body}</TBODY></TABLE></SECTION-2></SECTION-1></BODY></DOCUMENT>")
    p = tmp_path / "f.xml"
    p.write_text(xml, encoding="utf-8")
    tables, _ = mn.load_source_tables(str(p))
    return {a[0]: a[3] for a in tables[0].amounts}


def test_blank_row_with_a_total_word_in_a_value_cell_is_not_a_limit_r295b(tmp_path):
    flags = _flags(tmp_path, "<TR><TD>대여금</TD><TD></TD><TD>5,000,000</TD></TR>"
                             "<TR><TD></TD><TD>계</TD><TD>6,000,000</TD></TR>"
                             "<TR><TD></TD><TD>신한은행</TD><TD>7,000,000</TD></TR>",
                   head="<TR><TH>구분</TH><TH>적요</TH><TH>금액</TH></TR>")
    assert flags[6000000] is False          # the loader labels it '계' (R295-b)
    assert flags[7000000] is True           # a bank name in a value cell is no label: the limit
