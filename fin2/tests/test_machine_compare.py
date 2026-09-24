"""machine_compare: parser-independent source-XML vs report_lines comparison (no DB)."""
from __future__ import annotations

from fin2.verification import machine_compare as mc


def _xml(tmp_path, body: str) -> str:
    p = tmp_path / "f.xml"
    p.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
{body}
</SECTION-1></BODY></DOCUMENT>""", encoding="utf-8")
    return str(p)


def _section(title: str, *tables: str) -> str:
    return f"<SECTION-2><TITLE>{title}</TITLE>{''.join(tables)}</SECTION-2>"


def _title(text: str) -> str:
    return f"<TABLE><TR><TD>{text}</TD></TR><TR><TD>(단위 : 원)</TD></TR></TABLE>"


def _table(*rows: list[str], head: list[str] | None = None) -> str:
    out = "<TABLE>"
    if head:
        out += "<TR>" + "".join(f"<TD>{h}</TD>" for h in head) + "</TR>"
    for r in rows:
        out += "<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>"
    return out + "</TABLE>"


def _row(st, basis, order, label, value, col=0, cumulative=None, seq=0):
    return {"statement": st, "basis": basis, "table_seq": seq, "row_order": order,
            "label_raw": label, "col_index": col, "value_won": value, "is_cumulative": cumulative}


def test_clean_bs_with_note_column(tmp_path):
    # note references ('4,5', '6') sit in a '주석' column and must never be read as amounts
    body = _section("2. 연결재무제표", _title("연결 재무상태표"), _table(
        ["유동자산", "4,5", "1,000", "900"], ["현금", "6", "300", "200"], ["자산총계", "", "1,000", "900"],
        ["부채총계", "", "400", "300"], ["자본총계", "", "600", "600"],
        head=["과목", "주 석", "제 10 기", "제 9 기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("BS", "consolidated", i, lab, v) for i, (lab, v) in enumerate(
        (("유동자산", 1000), ("현금", 300), ("자산총계", 1000), ("부채총계", 400), ("자본총계", 600)))]
    res = mc.compare(rows, tables)
    assert res.verdict == "clean", res.findings
    assert res.counts["cells"] == 5


def test_bs_identity(tmp_path):
    body = _section("2. 연결재무제표", _title("연결 재무상태표"), _table(
        ["자산총계", "1,000"], ["부채총계", "400"], ["자본총계", "500"], head=["과목", "당기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("BS", "consolidated", i, lab, v) for i, (lab, v) in
            enumerate((("자산총계", 1000), ("부채총계", 400), ("자본총계", 500)))]
    assert [f["kind"] for f in mc.compare(rows, tables).findings] == ["bs_identity"]


def test_value_mismatch_and_missing_row(tmp_path):
    body = _section("2. 연결재무제표", _title("연결 재무상태표"), _table(
        ["유동자산", "1,000", "900"], ["현금", "300", "200"], ["자산총계", "1,000", "900"],
        head=["과목", "당기", "전기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("BS", "consolidated", 0, "유동자산", 1000),
            _row("BS", "consolidated", 2, "자산총계", 900)]          # took the prior column
    res = mc.compare(rows, tables)
    kinds = sorted(f["kind"] for f in res.findings)
    assert kinds == ["missing_row", "value"]
    v = next(f for f in res.findings if f["kind"] == "value")
    assert v["found_at"] == [1]                                      # the prior-period column


def test_quarter_cumulative_column_is_chosen_by_header(tmp_path):
    head = "<TR><TD ROWSPAN='2'></TD><TD COLSPAN='2'>제 22 기 3분기</TD><TD COLSPAN='2'>제 21 기 3분기</TD></TR>" \
           "<TR><TD>3 개 월</TD><TD>누 적</TD><TD>3개월</TD><TD>누적</TD></TR>"
    table = f"<TABLE>{head}<TR><TD>매출액</TD><TD>10</TD><TD>30</TD><TD>9</TD><TD>27</TD></TR></TABLE>"
    tables = mc.load_statement_tables(_xml(tmp_path, _section("2. 연결재무제표", _title("연결 손익계산서"), table)))
    ok = mc.compare([_row("IS", "consolidated", 0, "매출액", 30, cumulative=True)], tables)
    assert ok.verdict == "clean"
    bad = mc.compare([_row("IS", "consolidated", 0, "매출액", 10, cumulative=True)], tables)
    assert [f["kind"] for f in bad.findings] == ["value"]           # 3-month value loaded as cumulative


def test_detail_and_subtotal_subcolumns_form_one_period(tmp_path):
    head = "<TR><TD>과목</TD><TD COLSPAN='2'>제 65 (당)기</TD><TD COLSPAN='2'>제 64 (전)기</TD></TR>"
    table = (f"<TABLE>{head}<TR><TD>현금</TD><TD>5</TD><TD></TD><TD>4</TD><TD></TD></TR>"
             f"<TR><TD>자산총계</TD><TD></TD><TD>50</TD><TD></TD><TD>40</TD></TR></TABLE>")
    tables = mc.load_statement_tables(_xml(tmp_path, _section("2. 연결재무제표", _title("연결 재무상태표"), table)))
    res = mc.compare([_row("BS", "consolidated", 0, "현금", 5), _row("BS", "consolidated", 1, "자산총계", 50)], tables)
    assert res.verdict == "clean"


def test_amount_forms():
    assert mc.parse_amount("2,564원") == 2564.0
    assert mc.parse_amount("(1,234)") == -1234.0
    assert mc.parse_amount("-") == 0.0
    assert mc.parse_amount("") == mc._EMPTY
    assert mc.parse_amount("&cr;&cr;373,522") == 373522.0
    assert mc.parse_amount("2,263&cr;(75)&cr;5") == 2263.0              # supplementary values
    assert mc.parse_amount("주석 3") is None


SCE_HEAD = ["구분", "자본금", "이익잉여금", "합계"]


def _sce(rows):
    return _section("4. 재무제표", _title("자본변동표"), _table(*rows, head=SCE_HEAD))


def test_sce_identity_catches_dropped_sign_in_source(tmp_path):
    # closing retained earnings printed without parentheses (R162 pattern): -30 shown as 30
    body = _sce([["2024.01.01 (기초자본)", "100", "(10)", "90"],
                 ["당기순이익", "", "(20)", "(20)"],
                 ["2024.12.31 (기말자본)", "100", "30", "70"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = []
    for order, (lab, vals) in enumerate((("2024.01.01 (기초자본)", (100, -10, 90)),
                                         ("당기순이익", (None, -20, -20)),
                                         ("2024.12.31 (기말자본)", (100, 30, 70)))):
        for col, v in enumerate(vals):
            if v is not None:
                rows.append(_row("SCE", "separate", order, lab, v, col=col))
    res = mc.compare(rows, tables)
    assert [f["kind"] for f in res.findings] == ["sce_identity"]
    assert res.findings[0]["col"] == 1


def test_sce_sign_restored_by_loader_is_not_a_finding(tmp_path):
    body = _sce([["2024.01.01 (기초자본)", "100", "(10)", "90"],
                 ["당기순이익", "", "(20)", "(20)"],
                 ["2024.12.31 (기말자본)", "100", "30", "70"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = []
    for order, (lab, vals) in enumerate((("2024.01.01 (기초자본)", (100, -10, 90)),
                                         ("당기순이익", (None, -20, -20)),
                                         ("2024.12.31 (기말자본)", (100, -30, 70)))):
        for col, v in enumerate(vals):
            if v is not None:
                rows.append(_row("SCE", "separate", order, lab, v, col=col))
    res = mc.compare(rows, tables)
    assert res.verdict == "clean"
    assert res.counts["sign_restored"] == 1


def test_sce_subtotals_by_value_before_and_after_items(tmp_path):
    body = _sce([["2024.01.01 (기초자본)", "100", "50", "150"],
                 ["기타포괄손익", "", "5", "5"],                      # parent first (1 child)
                 ["재측정요소", "", "5", "5"],
                 ["당기순이익", "", "10", "10"],
                 ["총포괄손익", "", "15", "15"],                       # total after items
                 ["2024.12.31 (기말자본)", "100", "65", "165"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    assert mc.sce_identity(tables[0].rows) == []


def test_zero_row_and_appropriation_statement(tmp_path):
    body = _section("4. 재무제표", _title("손익계산서"), _table(
        ["매출액", "100", "90"], ["자본조정", "-", "-"], ["당기순이익", "10", "9"], head=["과목", "당기", "전기"]),
        _title("이익잉여금처분계산서"), _table(["미처분이익잉여금", "10", "9"], ["전기이월", "0", "0"],
                                            ["당기순이익", "10", "9"], head=["과목", "당기", "전기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    res = mc.compare([_row("IS", "separate", 0, "매출액", 100), _row("IS", "separate", 2, "당기순이익", 10)],
                     tables)
    assert [f["kind"] for f in res.findings] == ["zero_row"]      # appropriation table ignored


def test_notes_sections_are_not_statement_tables(tmp_path):
    body = _section("3. 연결재무제표 주석", _table(["매출액", "1", "2"], head=["과목", "당기", "전기"]))
    assert mc.load_statement_tables(_xml(tmp_path, body)) == []
    assert mc.compare([], []).verdict == "no_structure"
