"""R294 - a note cell that prints a won amount on its first line and only a foreign-currency amount or a
symbol on the following lines ('171,750,000&cr; USD 44,000,000', '84,350,000 &cr;$', '34,000,000 &cr;-')
was read by parse_amount as None and left no trace in note_lines, so the total row of a collateral /
guarantee table lost those columns (found by the verification scope note machine; 20210517000791 separate
table 31, 20191114002058 consolidated table 117, 20210812000251 consolidated table 94). The first line
is read, the whole printed cell stays in value_raw; the tail amount is not stored."""
from __future__ import annotations

from fin2.extract.report_lines import extract_report_lines, split_amount_with_tail

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
<P>담보제공자산 (원화단위:천원, 외화단위:USD)</P>
<TABLE>
<TR><TD>구분</TD><TD>장부금액</TD><TD>담보설정금액</TD><TD>채무금액</TD></TR>
<TR><TD>토지</TD><TD>40,181,100</TD><TD>90,000,000&cr; USD 25,000,000</TD><TD>80,000,000</TD></TR>
<TR><TD>건물</TD><TD>1,000</TD><TD>2,000 &cr;$</TD><TD>3,000 &cr;-</TD></TR>
<TR><TD>기계</TD><TD>4,000</TD><TD>5,000&cr; 한화 설명</TD><TD>6,000&cr; USD 1,2 (주1)</TD></TR>
<TR><TD>합계</TD><TD>230,431,897</TD><TD>171,750,000&cr; USD 44,000,000&cr; CAD 2,000,000</TD><TD>105,000,000 &cr;U</TD></TR>
</TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _rows(tmp_path):
    p = tmp_path / "n.xml"
    p.write_text(XML, encoding="utf-8")
    lines = extract_report_lines(p, rcept_no="29990101000001", corp_code="99000001",
                                 report_fiscal_year=2024, report_fiscal_period="FY",
                                 include_notes=True)
    return [l for l in lines if l.statement == "note"]


def test_split_amount_with_tail_is_narrow():
    f = split_amount_with_tail
    assert f("171,750,000\n USD 44,000,000\n CAD 2,000,000") == "171,750,000"
    assert f("84,350,000 \n$") == "84,350,000" and f("34,000,000 \n-") == "34,000,000"
    assert f("19,932,066 \nU") == "19,932,066" and f("105,000,000\n(CNY 128,000)") == "105,000,000"
    assert f("(6,469)\n=====") == "(6,469)"
    assert f("160,500,000USD 8,000,000") == "160,500,000" and f("116,473,320U") == "116,473,320"   # line break dropped
    assert f("1,234,5678") is None and f("1,234.5 USD 3") is None and f("1,234-5") is None
    assert f("5,000\n 한화 설명") is None                 # Korean text in the tail
    assert f("6,000\n USD 1,2 (주1)") is None             # a note reference in the tail
    assert f("USD 44,000,000\n 171,750,000") is None      # foreign amount first
    assert f("1,234") is None and f("") is None and f("2016 2015") is None   # no tail / not an amount


def test_tail_cells_keep_their_first_line_amount(tmp_path):
    rows = _rows(tmp_path)
    total = {l.col_index: l for l in rows if l.label_raw.strip() == "합계"}
    assert total[0].value_won == 230431897000                # unchanged plain cell
    assert total[1].value_won == 171750000000 and total[1].value_raw.startswith("171,750,000")
    assert "USD 44,000,000" in total[1].value_raw            # the printed text stays
    assert total[2].value_won == 105000000000
    land = {l.col_index: l for l in rows if l.label_raw.strip() == "토지"}
    assert land[1].value_won == 90000000000


def test_symbol_tails_and_refused_tails(tmp_path):
    rows = _rows(tmp_path)
    bld = {l.col_index: l for l in rows if l.label_raw.strip() == "건물"}
    assert bld[1].value_won == 2000000 and bld[2].value_won == 3000000
    mach = {l.col_index: l for l in rows if l.label_raw.strip() == "기계"}
    assert mach[0].value_won == 4000000                      # plain cell is read as before
    # tails with Korean text / a note reference are NOT read (R6): no number is invented
    assert all(l.value_won is None for c, l in mach.items() if c in (1, 2))


def test_cells_without_a_tail_do_not_change(tmp_path):
    rows = _rows(tmp_path)
    land = {l.col_index: l for l in rows if l.label_raw.strip() == "토지"}
    assert land[0].value_won == 40181100000 and land[0].value_raw is None
    assert land[2].value_won == 80000000000 and land[2].value_raw is None


def test_dollar_and_any_currency_code_tails_r294b():
    """R294-b: '$' / 'US$' / 'U$' amounts and any 2-4 capital letter code before an amount."""
    f = split_amount_with_tail
    assert f("8,080,500(TRY 25,000,000)") == "8,080,500" and f("2,000US$ 82,000") == "2,000"
    assert f("3,000 U$22,700,000") == "3,000" and f("4,000 $500,000") == "4,000"
    assert f("5,000 USD 4,650,000 DEM 1,285,000") == "5,000" and f("6,000 RMB 6,000,000") == "6,000"
    assert f("7,000 RS 90,000") == "7,000" and f("8,000 CNY - USD 4,000,000") == "8,000"
    # still refused: Korean / note references / bare numbers / a code without a real amount
    assert f("9,000 USD 1,000,000 (미주,USD 5,000,000)") is None
    assert f("1,000 - 101,259,961 140,641,247") is None
    assert f("1,234 NO 5") is None and f("1,234 ABC") is None and f("10,000 한화") is None
