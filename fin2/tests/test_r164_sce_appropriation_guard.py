"""R164(2026-09-22) regression test - an SCE table dropped whole because the
appropriation-statement guard cannot discriminate on SCE.

`_looks_like_appropriation()` is true when ① an appropriation account appears
AND ② no "real statement" account (`_REAL_STMT_ROW_RE`: 자산총계·매출액·
영업활동현금흐름...) appears. ② is a genuine discriminator for BS/IS/CF. For an
SCE it can NEVER match - SCE row labels are change reasons and the header row
carries equity component names. So every SCE whose labels contain
`미처분이익잉여금` (an ordinary equity component) was misread as an
appropriation statement and skipped by `_detect_body_statement_tables()`.

Measured: 한화오션 20170515004751 lost its separate SCE (74 source rows)
entirely while the consolidated SCE loaded fine - the asymmetry came from the
separate statement having a `미처분이익잉여금` column that the consolidated one
does not (campaign issue #30). Corpus scan (2015+): 127 filings / 131 tables /
4,279 source rows.

The fix does not remove the guard; it exempts tables that POSITIVELY present an
SCE header (`_looks_like_equity_changes_header`, the same content test R127/R148
already rely on).

Run: pytest fin2/tests/test_r164_sce_appropriation_guard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.report_lines import extract_report_lines  # noqa: E402
from fin2.extract.text import (  # noqa: E402
    _detect_body_statement_tables, _looks_like_appropriation,
    _looks_like_equity_changes_header,
)

# ─────────────────────────── synthetic document ───────────────────────────
# Equity component column names, as DART writes them in an SCE header row.
_SCE_COLS = ("자본금", "기타자본잉여금", "미처분이익잉여금", "자본 합계")


def _sce_table(title: str, *, with_approp_label: bool) -> str:
    """An SCE data table. `with_approp_label` puts the equity component names in
    the block header row's first cell, exactly as 한화오션 20170515004751 does
    ('미처분이익잉여금재평가차익' - two column names merged into one cell)."""
    header_first = "미처분이익잉여금재평가차익" if with_approp_label else "구분"
    head = "".join(f"<TD><P>{c}</P></TD>" for c in _SCE_COLS)
    rows = [
        f"<TR><TD><P>{header_first}</P></TD>{head}</TR>",
        "<TR><TD><P>2017.01.01 (기초자본)</P></TD>"
        "<TD><P>332,884,800,000</P></TD><TD><P>(16,797,720,223)</P></TD>"
        "<TD><P>(1,289,856,397,459)</P></TD><TD><P>453,244,719,128</P></TD></TR>",
        "<TR><TD><P>2017.03.31 (기말자본)</P></TD>"
        "<TD><P>332,884,800,000</P></TD><TD><P>(16,797,720,223)</P></TD>"
        "<TD><P>(1,289,856,397,459)</P></TD><TD><P>453,861,699,196</P></TD></TR>",
    ]
    return (f"<TABLE><TR><TD><P>{title}</P></TD></TR></TABLE>"
            f"<TABLE>{''.join(rows)}</TABLE>")


def _bs_table(title: str) -> str:
    return (f"<TABLE><TR><TD><P>{title}</P></TD></TR></TABLE>"
            "<TABLE>"
            "<TR><TD><P>자산총계</P></TD><TD><P>12,220,859,462,976</P></TD></TR>"
            "<TR><TD><P>자본총계</P></TD><TD><P>453,861,699,196</P></TD></TR>"
            "</TABLE>")


def _doc(*, with_approp_label: bool) -> etree._Element:
    """A 2015+ shaped document: '2. 연결재무제표' then '4. 재무제표'."""
    per = "제 18 기 1분기 2017.01.01 부터 2017.03.31 까지"
    xml = f"""<DOCUMENT>
      <SECTION-2><TITLE>2. 연결재무제표</TITLE>
        {_bs_table(f"연결 재무상태표 {per}")}
        {_sce_table(f"연결 자본변동표 {per}", with_approp_label=False)}
      </SECTION-2>
      <SECTION-2><TITLE>4. 재무제표</TITLE>
        {_bs_table(f"재무상태표 {per}")}
        {_sce_table(f"자본변동표 {per}", with_approp_label=with_approp_label)}
      </SECTION-2>
    </DOCUMENT>"""
    return etree.fromstring(xml.encode())


# ───────────────────── the predicate itself is unchanged ─────────────────────

def test_predicate_still_flags_a_real_appropriation_statement():
    """★가드를 약화시킨 게 아니라는 확인 — 처분계산서는 그대로 참이다."""
    approp = etree.fromstring(
        "<TABLE>"
        "<TR><TD><P>Ⅰ.미처분이익잉여금</P></TD><TD><P>110,890</P></TD></TR>"
        "<TR><TD><P>Ⅱ.이익잉여금처분액</P></TD><TD><P>1,000,000</P></TD></TR>"
        "</TABLE>".encode())
    assert _looks_like_appropriation(approp) is True


def test_sce_with_equity_component_label_still_trips_the_predicate():
    """★결함의 전제를 고정한다 — SCE 도 이 술어에는 여전히 걸린다.

    술어를 고친 게 아니므로 여기서 False 가 되면 수정 방식이 바뀐 것이다.
    이 술어의 ②(진짜 재무제표 계정 부재)는 SCE 에서 절대 성립하지 않는다.
    """
    tbl = etree.fromstring(_sce_table("자본변동표 제 18 기", with_approp_label=True)
                           .split("</TABLE><TABLE>")[1].join(["<TABLE>", ""])
                           .encode())
    assert _looks_like_appropriation(tbl) is True
    assert _looks_like_equity_changes_header(tbl) is True


# ─────────────────────────── the detector ───────────────────────────

def test_separate_sce_survives_the_appropriation_guard():
    """★핵심 — '미처분이익잉여금' 열을 가진 별도 SCE 가 더 이상 버려지지 않는다."""
    groups = _detect_body_statement_tables(
        _doc(with_approp_label=True), fin_type="A", include_sce=True)
    assert "SCE_S" in groups, "별도 SCE 가 처분계산서 가드에 걸려 유실됨(R164 회귀)"
    assert "SCE_C" in groups, "연결 SCE 가 이 수정으로 사라짐"


def test_asymmetry_is_gone():
    """연결에만 그 열이 있고/없고에 따라 결과가 갈리지 않는다.

    이슈#30 의 증상이 정확히 이 비대칭이었다 — 같은 필링에서 연결 SCE 185행은
    정상 적재, 별도 SCE 74행은 0행.
    """
    with_label = _detect_body_statement_tables(
        _doc(with_approp_label=True), fin_type="A", include_sce=True)
    without = _detect_body_statement_tables(
        _doc(with_approp_label=False), fin_type="A", include_sce=True)
    assert set(with_label) == set(without)


def test_other_statements_are_untouched():
    """BS 는 이 수정과 무관하게 그대로 잡힌다(가산적 수정 확인)."""
    groups = _detect_body_statement_tables(
        _doc(with_approp_label=True), fin_type="A", include_sce=True)
    assert "BS_C" in groups and "BS_S" in groups


def test_split_title_and_data_format_also_recovers_the_sce():
    """표제표와 데이터표가 **떨어져 있는** 서식에서도 별도 SCE 가 살아남는다.

    ★정직하게 적어둔다 — 이 테스트는 **두 번째 call site 를 단독으로 증명하지
    못한다.** 변이 검사 결과: 두 번째 call site 만 되돌려도 이 테스트는 통과한다.
    이 서식에서는 데이터표가 자기 인덱스에서도 `title_text_for_classify` 로 SCE 로
    분류돼 첫 번째 call site 가 같은 표를 잡기 때문이다(그래서 같은 물리 표가 두 번
    append 되는데, 그 중복은 R164 와 무관한 기존 성질이다 — 라벨을 '구분'으로 바꿔도
    같이 발생한다).

    두 번째 call site 는 런북의 "두 call site 모두 배선" 요구에 따라 대칭으로
    배선했고, **그 한쪽만이 결과를 가르는 서식은 만들어내지 못했다.** 그래서 이
    테스트가 고정하는 것은 "분리 서식에서도 SCE_S 가 나온다" 까지다.
    """
    per = "제 18 기 1분기 2017.01.01 부터 2017.03.31 까지"
    head = "".join(f"<TD><P>{c}</P></TD>" for c in _SCE_COLS)
    xml = f"""<DOCUMENT>
      <SECTION-2><TITLE>4. 재무제표</TITLE>
        {_bs_table(f"재무상태표 {per}")}
        <TABLE><TR><TD><P>자본변동표 {per}</P></TD></TR></TABLE>
        <TABLE><TR><TD><P>(단위 : 원)</P></TD></TR></TABLE>
        <TABLE>
          <TR><TD><P>미처분이익잉여금재평가차익</P></TD>{head}</TR>
          <TR><TD><P>2017.01.01 (기초자본)</P></TD>
            <TD><P>332,884,800,000</P></TD><TD><P>(16,797,720,223)</P></TD>
            <TD><P>(1,289,856,397,459)</P></TD><TD><P>453,244,719,128</P></TD></TR>
          <TR><TD><P>2017.03.31 (기말자본)</P></TD>
            <TD><P>332,884,800,000</P></TD><TD><P>(16,797,720,223)</P></TD>
            <TD><P>(1,289,856,397,459)</P></TD><TD><P>453,861,699,196</P></TD></TR>
        </TABLE>
      </SECTION-2>
    </DOCUMENT>"""
    groups = _detect_body_statement_tables(
        etree.fromstring(xml.encode()), fin_type="B", include_sce=True)
    assert "SCE_S" in groups, (
        "표제/데이터 분리 서식의 별도 SCE 가 처분계산서 가드에 걸려 유실됨 "
        "— 두 번째 call site 미배선(R164)")


def test_guard_still_drops_an_appropriation_table_titled_as_a_statement():
    """★면제는 '내용이 SCE 인 표' 에만 적용된다 — 처분계산서가 재무제표 표제를
    달고 있으면 여전히 배제한다(계양전기 20220420000289 계열, R164 로 뚫리면 안 됨).
    """
    per = "제 21 기 2019.01.01 부터 2019.12.31 까지"
    xml = f"""<DOCUMENT>
      <SECTION-2><TITLE>4. 재무제표</TITLE>
        <TABLE><TR><TD><P>현금흐름표 {per}</P></TD></TR></TABLE>
        <TABLE>
          <TR><TD><P>Ⅰ.미처분이익잉여금</P></TD><TD><P>5,282,975,386</P></TD></TR>
          <TR><TD><P>Ⅱ.이익잉여금처분액</P></TD><TD><P>1,000,000,000</P></TD></TR>
        </TABLE>
      </SECTION-2>
    </DOCUMENT>"""
    groups = _detect_body_statement_tables(
        etree.fromstring(xml.encode()), fin_type="B", include_sce=True)
    assert "CF_S" not in groups, "처분계산서가 CF 로 적재됨 — 가드가 뚫렸다"


# ─────────────────────── real filing (issue #30) ───────────────────────

_HHO_2017Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00111704_한화오션/quarter/2017/20170515004751.xml"
)


def test_hanwha_ocean_2017q1_separate_sce_recovered():
    """실측 필링 — 별도 SCE 가 복구되고 기말 자본합계가 **별도 BS 자본총계와 일치**한다.

    앵커가 SCE 자신이 아니라 같은 필링의 BS 라는 점이 중요하다(자기증명 금지).
    """
    if not _HHO_2017Q1.exists():
        return
    lines = extract_report_lines(
        _HHO_2017Q1, rcept_no="20170515004751", corp_code="00111704",
        report_fiscal_year=2017, report_fiscal_period="Q1")

    sce = [l for l in lines if l.statement == "SCE" and l.basis == "separate"]
    assert sce, "별도 SCE 가 여전히 0행(R164 회귀)"

    closing = [l for l in sce
               if l.label_raw.strip() == "2017.03.31 (기말자본)"
               and (l.col_label or "").endswith("자본 합계")]
    assert closing, "기말자본 합계 셀을 못 찾음"

    bs_equity = [l for l in lines
                 if l.statement == "BS" and l.basis == "separate"
                 and (l.label_raw or "").replace(" ", "") == "자본총계"
                 and (l.col_index or 0) == 0]
    assert bs_equity, "별도 BS 자본총계(앵커)를 못 찾음"
    assert closing[0].value_won == bs_equity[0].value_won == 453_861_699_196

    # 연결 SCE 는 이 수정 전에도 정상이었다 — 회귀 없음 확인.
    con = [l for l in lines if l.statement == "SCE" and l.basis == "consolidated"]
    assert con, "연결 SCE 가 이 수정으로 사라짐"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))


# ───────────────── R164-b: the positive-evidence window ─────────────────
# `_looks_like_equity_changes_header` originally read only rows[0:2]. Formats
# whose row 0 is a COLSPAN banner (`['', '자본']`) and whose equity component
# names sit on row 2 therefore failed the test, so the R164 exemption did not
# apply and the SCE was still dropped: 119 filings / 145 tables remained.
#
# The predicate is shared by R127/R127b/R148, so widening it was verified over
# the whole 2015+ corpus (104,533 filings) by diffing table assignments before
# and after: 152 filings changed, every one of them a GAIN
# (142 code-level + 34 an extra SCE_S table), 0 lost, 0 removed, 0 reassigned.

def _sce_rows_with_banner() -> str:
    """Row 0 = COLSPAN banner, row 1 = group tier, row 2 = the component names.
    Shape taken from 삼진엘앤디 20260513000016 / 삼화전자공업 20160330003638."""
    return ("<TABLE>"
            "<TR><TD><P></P></TD><TD><P>자본</P></TD></TR>"
            "<TR><TD><P>지배기업의 소유주에게 귀속되는 지분</P></TD>"
            "<TD><P>비지배지분</P></TD><TD><P>자본 합계</P></TD></TR>"
            "<TR><TD><P>자본금</P></TD><TD><P>연결자본잉여금</P></TD>"
            "<TD><P>연결기타포괄손익누계액</P></TD><TD><P>연결이익잉여금</P></TD></TR>"
            "<TR><TD><P>2025.01.01 (기초자본)</P></TD><TD><P>12,479,616,000</P></TD>"
            "<TD><P>50,980,946,410</P></TD><TD><P>1,415,054,923</P></TD>"
            "<TD><P>(35,110,515,764)</P></TD></TR>"
            "</TABLE>")


def test_equity_header_seen_when_component_names_are_on_the_third_row():
    """★R164-b — 배너 행이 앞에 붙어도 SCE 로 인식한다(종전 두 행만 봐서 실패)."""
    tbl = etree.fromstring(_sce_rows_with_banner().encode())
    assert _looks_like_equity_changes_header(tbl) is True


def test_equity_header_tokens_cover_spelled_out_equity_components():
    """★R164-b — `기타불입자본`·`기타자본구성요소` 도 자본 구성요소 명칭이다.

    실측 KD 20150515001189 별도 SCE 열이름은 '자본금·기타불입자본·기타자본구성요소·
    미처분이익잉여금(미처리결손금)·자본 합계' 인데, 옛 목록으로는 `자본금` 과
    (미처분)`이익잉여금` 2개만 걸려 임계값(3) 미달이었다.
    """
    tbl = etree.fromstring(
        "<TABLE>"
        "<TR><TD><P>자본금</P></TD><TD><P>기타불입자본</P></TD>"
        "<TD><P>기타자본구성요소</P></TD>"
        "<TD><P>미처분이익잉여금(미처리결손금)</P></TD>"
        "<TD><P>자본 합계</P></TD></TR>"
        "<TR><TD><P>2013.01.01 (기초자본)</P></TD><TD><P>8,809,504,200</P></TD>"
        "<TD><P>18,237,515,177</P></TD><TD><P>(20,202,226,206)</P></TD>"
        "<TD><P>6,844,793,171</P></TD></TR>"
        "</TABLE>".encode())
    assert _looks_like_equity_changes_header(tbl) is True


def test_equity_header_still_rejects_a_plain_cashflow_table():
    """★넓힌 창이 아무 표나 SCE 로 보지 않는다 — R127 이 지키던 경계."""
    tbl = etree.fromstring(
        "<TABLE>"
        "<TR><TD><P>과 목</P></TD><TD><P>당기</P></TD><TD><P>전기</P></TD></TR>"
        "<TR><TD><P>Ⅰ.영업활동현금흐름</P></TD><TD><P>1,111,111,111</P></TD>"
        "<TD><P>2,222,222,222</P></TD></TR>"
        "<TR><TD><P>당기순이익</P></TD><TD><P>333,333,333</P></TD>"
        "<TD><P>444,444,444</P></TD></TR>"
        "</TABLE>".encode())
    assert _looks_like_equity_changes_header(tbl) is False


def test_equity_header_still_rejects_a_balance_sheet_header():
    """BS 헤더('과목/당기말/전기말')에는 자본 구성요소 열이름이 없다."""
    tbl = etree.fromstring(
        "<TABLE>"
        "<TR><TD><P>과 목</P></TD><TD><P>제 18 기말</P></TD>"
        "<TD><P>제 17 기말</P></TD></TR>"
        "<TR><TD><P>자산총계</P></TD><TD><P>9,999,999,999</P></TD>"
        "<TD><P>8,888,888,888</P></TD></TR>"
        "</TABLE>".encode())
    assert _looks_like_equity_changes_header(tbl) is False
