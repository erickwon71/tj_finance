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
    kinds = [f["kind"] for f in res.findings]
    # mc10: identity findings are recorded (layer-3 backlog) but do not block — every cell matches
    assert "sign_omitted" in kinds and res.verdict == "clean"
    f = next(f for f in res.findings if f["kind"] == "sign_omitted" and f["col"] == 1)
    assert f["explain"] == "sign" and f["row"].startswith("2024.12.31") and f["value"] == 30.0


def test_flipping_the_total_change_row_is_not_a_dropped_sign(tmp_path):
    # 20180515001512 (2026-10-03): the source prints closing == opening although the changes
    # add up to +3,629,919,539. Flipping "자본 증가(감소) 합계" (the total of the rows above)
    # cancels them and "closes" the column - mc5 reported it as a dropped sign (R162) and the
    # cell flapped closed/re-registered across reloads. It is source arithmetic.
    src = (("2017.01.01 (기초자본)", (215370991037,)),
           ("당기순이익(손실)", (8806886098,)),
           ("기타포괄손익", (-48110769,)),
           ("총포괄손익", (8758775329,)),
           ("배당금지급", (-5128855790,)),
           ("자본 증가(감소) 합계", (3629919539,)),
           ("2017.03.31 (기말자본)", (215370991037,)))
    fmt = lambda v: f"({-v:,})" if v < 0 else f"{v:,}"  # noqa: E731
    body = _section("4. 재무제표", _title("자본변동표"),
                    _table(*[[lab, *map(fmt, vals)] for lab, vals in src], head=["구분", "총계"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("SCE", "separate", order, lab, v, col=col)
            for order, (lab, vals) in enumerate(src) for col, v in enumerate(vals) if v is not None]
    res = mc.compare(rows, tables)
    assert "sign_omitted" not in {f["kind"] for f in res.findings}
    assert res.verdict == "clean"


def test_plain_row_equal_to_the_others_is_still_a_sign_candidate(tmp_path):
    # the mc6 total-row exclusion must not hide R162 itself: dividends printed without
    # parentheses that happen to equal net income + OCI (net change 0, closing == opening)
    src = (("2024.01.01 (기초자본)", (500000000000,)),
           ("당기순이익", (7000000000,)),
           ("기타포괄손익", (3000000000,)),
           ("배당금지급", (10000000000,)),
           ("2024.12.31 (기말자본)", (500000000000,)))
    body = _section("4. 재무제표", _title("자본변동표"),
                    _table(*[[lab, f"{v:,}"] for lab, (v,) in src], head=["구분", "총계"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("SCE", "separate", order, lab, v) for order, (lab, (v,)) in enumerate(src)]
    res = mc.compare(rows, tables)
    f = [f for f in res.findings if f["kind"] == "sign_omitted"]
    assert len(f) == 1 and f[0]["row"] == "배당금지급"


def test_sce_arithmetic_of_the_source_alone_does_not_block(tmp_path):
    # capital rises with no change row (source omission): DB equals the source everywhere
    body = _sce([["2024.01.01 (기초자본)", "100", "10", "110"],
                 ["당기순이익", "", "5", "5"],
                 ["2024.12.31 (기말자본)", "125", "15", "140"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = []
    for order, (lab, vals) in enumerate((("2024.01.01 (기초자본)", (100, 10, 110)),
                                         ("당기순이익", (None, 5, 5)),
                                         ("2024.12.31 (기말자본)", (125, 15, 140)))):
        for col, v in enumerate(vals):
            if v is not None:
                rows.append(_row("SCE", "separate", order, lab, v, col=col))
    res = mc.compare(rows, tables)
    assert res.verdict == "clean"
    assert {f["kind"] for f in res.findings} == {"sce_arith"}


def test_sce_sign_restored_in_db_is_a_finding(tmp_path):
    # mc9 (R0-2): layer 2 must hold the printed sign; a restored sign in the DB is a value finding
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
    assert res.verdict == "mismatch"
    assert [(f["kind"], f["src"], f["db"]) for f in res.findings if f["kind"] == "value"] == [("value", 30.0, -30)]
    assert not res.counts.get("sign_restored")


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
    assert res.verdict == "clean"                                  # value-neutral: recorded, not blocking


def test_notes_sections_are_not_statement_tables(tmp_path):
    body = _section("3. 연결재무제표 주석", _table(["매출액", "1", "2"], head=["과목", "당기", "전기"]))
    assert mc.load_statement_tables(_xml(tmp_path, body)) == []
    assert mc.compare([], []).verdict == "no_structure"


def test_income_breakdown_tables_in_statement_section_are_not_unmatched(tmp_path):
    body = _section("2. 연결재무제표", _title("제56기 : 2016년 01월 01일부터"), _table(
        ["Ⅰ.예치금이자", "10", "9"], ["Ⅱ.증권이자", "20", "19"], ["1.국채이자", "5", "4"], head=["과목", "당기", "전기"]),
        _title("(단위: 천원)"), _table(["1. 처분전이익잉여금", "10", "9"], ["전기이월이익잉여금", "3", "2"],
                                     ["당기순이익", "7", "7"], head=["과목", "당기", "전기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    assert mc.compare([], tables).findings == []


def test_findings_to_issues_are_unique_cells():
    from fin2.verification import machine_pass as mp
    f = [{"kind": "missing_row", "basis": "separate", "statement": "SCE", "label": "배당", "cells": [0.0, -7.0]},
         {"kind": "missing_row", "basis": "separate", "statement": "SCE", "label": "배당", "cells": [-9.0]},
         {"kind": "value", "basis": "separate", "statement": "BS", "label": "현금", "db": 9, "src": 5.0, "src_col": 0,
          "header": "당기", "found_at": [1], "flipped_at": [], "scale": 1},
         {"kind": "sce_identity", "basis": "separate", "statement": "SCE"}]
    items = mp.findings_to_issues(f)
    assert [i["account_label"] for i in items] == ["배당", "배당 (#2)", "현금"]
    assert items[0]["source_value_raw"] == "(7)" and items[2]["error_type"] == "period_misassign"


def test_bs_identity_ignores_grand_total_labels(tmp_path):
    body = _section("4. 재무제표", _title("재무상태표"), _table(
        ["자산총계", "1,000"], ["부채총계", "400"], ["자본총계", "600"], ["자본과부채총계", "1,000"], head=["과목", "당기"]))
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("BS", "separate", i, lab, v) for i, (lab, v) in
            enumerate((("자산총계", 1000), ("자본과부채총계", 1000), ("부채총계", 400), ("자본총계", 600)))]
    assert mc.compare(rows, tables).verdict == "clean"


def test_repeated_block_labels_repair_to_the_agreeing_row(tmp_path):
    # the DB skipped the all-dash row of the first block, so difflib pairs the second
    # block's '당기순이익' with the first block's row; values put it back
    body = _sce([["2023.01.01 (기초자본)", "100", "10", "110"],
                 ["자본조정", "-", "-", "-"],
                 ["당기순이익", "", "5", "5"],
                 ["2023.12.31 (기말자본)", "100", "15", "115"],
                 ["2024.01.01 (기초자본)", "100", "15", "115"],
                 ["당기순이익", "", "7", "7"],
                 ["2024.12.31 (기말자본)", "100", "22", "122"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    data = (("2023.01.01 (기초자본)", (100, 10, 110)), ("당기순이익", (None, 5, 5)),
            ("2023.12.31 (기말자본)", (100, 15, 115)), ("2024.01.01 (기초자본)", (100, 15, 115)),
            ("당기순이익", (None, 7, 7)), ("2024.12.31 (기말자본)", (100, 22, 122)))
    rows = []
    for order, (lab, vals) in enumerate(data):
        for col, v in enumerate(vals):
            if v is not None:
                rows.append(_row("SCE", "separate", order, lab, v, col=col))
    res = mc.compare(rows, tables)
    assert not [f for f in res.findings if f["kind"] == "value"], res.findings


def test_eps_child_rows_under_eps_section_are_unscaled(tmp_path):
    # 흥국화재 20230515002741: a 백만원 IS whose EPS lines are '(1) 기본주당이익 > 1. 보통주'. The
    # child label lacks '주당', but the loader stores it unscaled (won per share) via the section path.
    body = _section("4. 재무제표", _title("포괄손익계산서"), _table(
        ["매출", "10,000"], ["당기순이익", "1,200"], ["(1) 기본주당이익", ""], ["1. 보통주", "1,457"],
        head=["과목", "당기"]))
    body = body.replace("(단위 : 원)", "(단위 : 백만원)")
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("IS", "separate", 0, "매출", 10_000_000_000), _row("IS", "separate", 1, "당기순이익", 1_200_000_000),
            dict(_row("IS", "separate", None, "1. 보통주", 1457), section_path="(1) 기본주당이익")]
    res = mc.compare(rows, tables)
    assert not [f for f in res.findings if f["kind"] == "value"], res.findings
    # without the section path the same cell reads as 1,457 백만원 and is flagged
    rows[2].pop("section_path")
    assert [f["label"] for f in mc.compare(rows, tables).findings if f["kind"] == "value"] == ["1. 보통주"]


def test_identity_tolerance_is_half_the_terms_rounded_up():
    # R0-1 2항 (2026-10-09): n printed numbers rounded to the display unit can be off by n/2
    assert [mc.identity_tolerance(n) for n in (1, 2, 3, 4, 7, 8)] == [1, 1, 2, 2, 4, 4]


def test_label_date_and_block_end_labels(tmp_path):
    assert mc.label_date("2023.12.31 (기말자본)") == "2023.12.31"
    assert mc.label_date("2023년 3월 1일") == "2023.03.01"
    assert mc.label_date("기말자본") is None
    body = _sce([["2023.01.01 (기초자본)", "100", "10", "110"], ["배당", "", "(5)", "(5)"],
                 ["2023.12.31 (기말자본)", "100", "5", "105"],
                 ["2024.01.01 (기초자본)", "100", "5", "105"], ["배당", "", "(6)", "(6)"],
                 ["2024.12.31 (기말자본)", "100", "(1)", "99"]])
    rows = mc.load_statement_tables(_xml(tmp_path, body))[0].rows
    ends = mc.block_end_labels(rows)
    assert ends[1] == "2023.12.31 (기말자본)" and ends[4] == "2024.12.31 (기말자본)"


def test_sce_value_finding_names_its_block_and_db_column(tmp_path):
    # '배당' repeats in both year blocks; the finding must say which block and the DB column
    body = _sce([["2023.01.01 (기초자본)", "100", "10", "110"], ["배당", "", "(5)", "(5)"],
                 ["2023.12.31 (기말자본)", "100", "5", "105"],
                 ["2024.01.01 (기초자본)", "100", "5", "105"], ["배당", "", "(6)", "(6)"],
                 ["2024.12.31 (기말자본)", "100", "(1)", "99"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    src = ((100, 10, 110), (None, -5, -5), (100, 5, 105), (100, 5, 105), (None, -6, -60), (100, -1, 99))
    labels = ["2023.01.01 (기초자본)", "배당", "2023.12.31 (기말자본)",
              "2024.01.01 (기초자본)", "배당", "2024.12.31 (기말자본)"]
    rows = [dict(_row("SCE", "separate", o, labels[o], v, col=c), col_label=SCE_HEAD[c + 1])
            for o, vals in enumerate(src) for c, v in enumerate(vals) if v is not None]
    res = mc.compare(rows, tables)
    v = next(f for f in res.findings if f["kind"] == "value")
    assert v["block_end"] == "2024.12.31 (기말자본)" and v["db_col"] == "합계"
    from fin2.verification import machine_pass as mp
    item = next(i for i in mp.findings_to_issues(res.findings, kinds=("value",)))
    assert item["column_label"] == "합계 @ 2024.12.31" and item["account_label"] == "배당"


def test_source_arithmetic_is_marked_and_becomes_a_source_defect_issue(tmp_path):
    # capital rises with no change row: D-calc and S-calc both open (verify_prompt I3)
    body = _sce([["2024.01.01 (기초자본)", "100", "10", "110"],
                 ["당기순이익", "", "5", "5"],
                 ["2024.12.31 (기말자본)", "125", "15", "140"]])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    rows = [_row("SCE", "separate", o, lab, v, col=c)
            for o, (lab, vals) in enumerate((("2024.01.01 (기초자본)", (100, 10, 110)),
                                              ("당기순이익", (None, 5, 5)),
                                              ("2024.12.31 (기말자본)", (125, 15, 140))))
            for c, v in enumerate(vals) if v is not None]
    res = mc.compare(rows, tables)
    assert res.verdict == "clean"
    arith = [f for f in res.findings if f["kind"] == "sce_arith"]
    assert arith and all(f["src_broken"] for f in arith)
    from fin2.verification import machine_pass as mp
    items = mp.arith_issues(res)
    assert {i["error_type"] for i in items} == {"source_defect"}
    assert items[0]["account_label"] == "2024.12.31 (기말자본)"
    assert items[0]["column_label"].endswith("@ 2024.12.31 #항등식")


def test_findings_to_issues_leave_the_column_empty_outside_sce():
    from fin2.verification import machine_pass as mp
    f = [{"kind": "value", "basis": "separate", "statement": "IS", "label": "매출액", "db": 9, "src": 5.0,
          "src_col": 0, "header": "제78(당)기1분기", "found_at": [], "flipped_at": [], "scale": 1}]
    assert "column_label" not in mp.findings_to_issues(f)[0]


def test_recheck_label_suffixes_are_stripped():
    from fin2.verification import ops
    assert ops._strip_label_disambiguator("1. 보통주 (#2)") == "1. 보통주"
    assert ops._strip_label_disambiguator("배당 [2023]") == "배당"
    assert ops._normalize_column_label("이익잉여금 @ 2023.12.31 #항등식") == "이익잉여금"


def _sce_rows(blocks, shift=0):
    rows, order = [], 0
    for lab, vals in blocks:
        for col, v in enumerate(vals):
            if v is not None:
                rows.append(_row("SCE", "separate", order, lab, v, col=col + shift))
        order += 1
    return rows


def test_sce_columns_numbered_from_one_are_aligned_by_value(tmp_path):
    # 00107613 2023Q1 (mc8): report_lines numbered the SCE columns from 1 (no column 0) while the
    # source has no note column - every cell was compared one column to the right (52 findings)
    src = [("2024.01.01 (기초자본)", (100, 10, 110)), ("당기순이익", (None, 5, 5)),
           ("2024.12.31 (기말자본)", (100, 15, 115))]
    body = _sce([[lab, *("" if v is None else f"{v:,}" for v in vals)] for lab, vals in src])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    res = mc.compare(_sce_rows(src, shift=1), tables)
    assert res.verdict == "clean" and not res.findings


def test_flipped_cells_are_findings_whatever_the_print(tmp_path):
    # mc9 (R0-2): a dividend printed without parentheses that the DB stores negative is a finding,
    # even when the DB sign closes its block
    src = [("2023.01.01 (기초자본)", (100, 50, 150)), ("당기순이익", (None, 7, 7)),
           ("2023.12.31 (기말자본)", (100, 60, 160)),          # 50 + 7 != 60: source arithmetic
           ("2024.01.01 (기초자본)", (100, 60, 160)), ("배당금지급", (None, 10, 10)),
           ("2024.12.31 (기말자본)", (100, 50, 150))]
    body = _sce([[lab, *("" if v is None else f"{v:,}" for v in vals)] for lab, vals in src])
    tables = mc.load_statement_tables(_xml(tmp_path, body))
    db = [(lab, tuple(-v if lab == "배당금지급" and v else v for v in vals)) for lab, vals in src]
    res = mc.compare(_sce_rows(db), tables)
    assert {f["src_col"] for f in res.findings if f["kind"] == "value"} == {1, 2}
    assert not res.counts.get("sign_restored")
    # a cell PRINTED negative that the DB stores positive is never a restoration
    src2 = [("2024.01.01 (기초자본)", (100, 60, 160)), ("배당금지급", (None, -10, -10)),
            ("2024.12.31 (기말자본)", (100, 70, 170))]
    body2 = _sce([[lab, *("" if v is None else (f"({-v:,})" if v < 0 else f"{v:,}") for v in vals)]
                  for lab, vals in src2])
    tables2 = mc.load_statement_tables(_xml(tmp_path, body2))
    db2 = [(lab, tuple(-v if lab == "배당금지급" and v else v for v in vals)) for lab, vals in src2]
    res2 = mc.compare(_sce_rows(db2), tables2)
    assert {f["src_col"] for f in res2.findings if f["kind"] == "value"} == {1, 2}


class _StubConn:
    """conn.execute(...).fetchall() -> the given layer3_cell_corrections rows."""
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_a, **_k):
        rows = self.rows

        class _R:
            def fetchall(self):
                return rows
        return _R()


def test_sign_omitted_with_layer3_correction_gets_no_issue():
    # R0-2 (2026-10-10): layer 2 keeps the printed 7; a layer-3 correction already flips it, so
    # the machine registers nothing. Without the correction it registers a source_defect.
    from fin2.verification import machine_pass as mp
    f = {"kind": "sign_omitted", "basis": "separate", "row": "배당금지급", "value": 7.0, "scale": 1,
         "header": "이익잉여금", "col": 1, "from": "2022.01.01 (기초자본)", "to": "2022.12.31 (기말자본)",
         "diff": 14.0}
    res = mc.Result("mismatch", mc.Counter(), [dict(f)])
    mc.mark_layer3_covered(_StubConn([("separate", "배당금지급", 7, -7)]), "r", res)
    assert res.findings[0]["l3_covered"] is True and mp.sign_issues(res) == []
    res2 = mc.Result("mismatch", mc.Counter(), [dict(f)])
    mc.mark_layer3_covered(_StubConn([("separate", "배당금지급", 7, 7)]), "r", res2)
    issues = mp.sign_issues(res2)
    assert [(i["error_type"], i["rule_id"], i["db_value"]) for i in issues] == [("source_defect", "R0-2", 7)]
