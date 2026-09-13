"""
R88 — `parser/xml/table_extractor.py::parse_header_columns()`/`select_by_header_columns()`
단위테스트. THEAD의 COLSPAN/ROWSPAN 그리드를 읽어 위치→회계기간 맵을 만드는 신규
경로(사용자 제안, 설계: docs/plans/report_lines_header_grid_column_map_design_
2026-09-09.md) — cum_map/multicol/else(R85~R87) 3갈래 추측을 헤더 구조를 먼저 읽는
방식으로 대체한다.

실측 카탈로그(설계문서 §1) 6개 형태를 합성 XML로 재현 — 실제 필링 파일 기반 회귀는
`fin2/tests/test_report_lines.py`(R85~R87 테스트가 이 경로를 그대로 타면서 이미 검증)
가 담당한다. 이 파일은 `parse_header_columns` 자체의 알고리즘을 원문 파일 없이도
고정하기 위한 것.

실행: pytest fin2/tests/test_header_grid_column_map_r88.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from parser.xml.table_extractor import (  # noqa: E402
    parse_header_columns, select_by_header_columns, extract_rows,
)


def _table(thead_xml: str, body_rows_xml: str) -> etree._Element:
    xml = f"<TABLE><THEAD>{thead_xml}</THEAD><TBODY>{body_rows_xml}</TBODY></TABLE>"
    return etree.fromstring(xml)


def test_plain_n_column_no_colspan():
    """삼성전자 2017Q1 CF류 — COLSPAN 없는 순수 4열."""
    thead = """
    <TR><TH>　</TH><TH>제 49 기 1분기</TH><TH>제 48 기 1분기</TH><TH>제 48 기</TH><TH>제 47 기</TH></TR>
    """
    t = _table(thead, "<TR><TD>영업활동 현금흐름</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert [(c.position, c.period_rank, c.subtype, c.is_note) for c in cols] == [
        (0, 0, None, False), (1, 1, None, False), (2, 2, None, False), (3, 3, None, False)]


def test_two_tier_three_month_cumulative():
    """삼성전자 2025H1 IS류 — ROWSPAN 라벨 + COLSPAN=2 기간그룹 + 하단 3개월/누적."""
    thead = """
    <TR>
      <TH ROWSPAN="2">　</TH>
      <TH COLSPAN="2">제 57 기 반기</TH>
      <TH COLSPAN="2">제 56 기 반기</TH>
    </TR>
    <TR><TH>3개월</TH><TH>누적</TH><TH>3개월</TH><TH>누적</TH></TR>
    """
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    got = [(c.position, c.period_rank, c.subtype) for c in cols]
    assert got == [(0, 0, "three_month"), (1, 0, "cumulative"),
                   (2, 1, "three_month"), (3, 1, "cumulative")]


def test_merge_group_no_subtype_text():
    """삼성생명류 — COLSPAN=2 인데 하위 구분 텍스트가 없음(명세/소계 병합군)."""
    thead = """
    <TR><TH>과목</TH><TH COLSPAN="2">제 61 (당) 기</TH>
        <TH COLSPAN="2">제 60 (전) 기</TH><TH COLSPAN="2">제 59 (전전) 기</TH></TR>
    """
    t = _table(thead, "<TR><TD>가.당기순이익</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    ranks = {c.position: c.period_rank for c in cols}
    subtypes = {c.position: c.subtype for c in cols}
    assert ranks == {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2}
    assert all(s is None for s in subtypes.values())


def test_note_column_excluded_label_fixed_at_one():
    """한화손해보험류 — 라벨 바로 다음에 명시적 "주석" 열. 라벨은 1개만, 주석열은
    is_note=True 로 자기 위치(position=0)를 그대로 갖는다(더 이상 라벨로 흡수 안 함)."""
    thead = """
    <TR><TH>과목</TH><TH>주석</TH><TH>제76(당)기</TH><TH>제75(전)기</TH></TR>
    """
    t = _table(thead, "<TR><TD>당기순이익</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert cols[0].is_note is True and cols[0].position == 0
    assert [(c.position, c.period_rank) for c in cols[1:]] == [(1, 0), (2, 1)]


def test_no_thead_falls_back():
    xml = "<TABLE><TBODY><TR><TD>매출액</TD><TD>100</TD><TD>90</TD></TR></TBODY></TABLE>"
    t = etree.fromstring(xml)
    assert parse_header_columns(t) is None


def test_headerless_pre2015_header_row_in_tbody():
    """R88 §7 확장(2026-09-10) — THEAD 없이 헤더행이 TBODY 선두 TD 행으로 오는 구서식
    (pre-2015 K-GAAP 등). 진짜 금액 데이터 행("매출액" 등)을 만나면 헤더 수집을
    멈춘다."""
    xml = (
        "<TABLE><TBODY>"
        "<TR><TD>구분</TD><TD>제 34 기</TD><TD>제 33 기</TD></TR>"
        "<TR><TD>매출액</TD><TD>100</TD><TD>90</TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    cols = parse_header_columns(t)
    assert cols is not None
    assert [(c.position, c.period_rank, c.subtype) for c in cols] == [
        (0, 0, None), (1, 1, None)]


def test_headerless_multi_row_header_three_month_cumulative():
    """THEAD 없이 2행짜리 헤더(기간 + 3개월/누적)가 TBODY 선두에 오는 경우 —
    ROWSPAN/COLSPAN 그리드 해석은 THEAD 경로와 동일하게 작동해야 한다."""
    xml = (
        "<TABLE><TBODY>"
        '<TR><TD ROWSPAN="2">구분</TD><TD COLSPAN="2">제 34 기</TD></TR>'
        "<TR><TD>3개월</TD><TD>누적</TD></TR>"
        "<TR><TD>매출액</TD><TD>10</TD><TD>20</TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    cols = parse_header_columns(t)
    assert cols is not None
    assert select_by_header_columns(cols, [10, 20]) == {0: 20}   # 누적(20) 채택


def test_headerless_no_marker_row_not_absorbed_as_header():
    """헤더행처럼 보이지만 기간패턴/서브타입 마커가 전혀 없는 행("자산" 류 섹션 헤더)은
    헤더로 흡수하면 안 된다 — R5(header_hint)와 다른 개념이므로 여기서 폴백돼야 한다."""
    xml = "<TABLE><TBODY><TR><TD>자산</TD></TR><TR><TD>매출액</TD><TD>100</TD></TR></TBODY></TABLE>"
    t = etree.fromstring(xml)
    assert parse_header_columns(t) is None


def test_headerless_banner_rows_skipped_before_real_header():
    """R95(2026-09-12) — THEAD 없는 구서식 표에 표제목("재무상태표")·기준일 캡션·
    "회사명 : (주)OOO / (단위 : 원)" 같은 COLSPAN 병합 배너행이 실제 헤더행 앞에
    여러 줄 끼어 있어도, `<COLGROUP>`이 선언한 총 열수(6) 대비 물리 셀 수가 적은
    행(=배너/캡션)은 건너뛰고 진짜 헤더행("계정명｜주석｜당기(2열)｜전기(2열)")까지
    도달해야 한다. 실측: 00186939 특수건설 20151116001903 재무상태표(미착품 등
    당기값이 원문에 없는데 전기값이 당기로 오적재되던 원인)."""
    xml = (
        "<TABLE><COLGROUP><COL/><COL/><COL/><COL/><COL/><COL/></COLGROUP><TBODY>"
        '<TR><TD COLSPAN="6">재무상태표</TD></TR>'
        '<TR><TD COLSPAN="6"></TD></TR>'
        '<TR><TD COLSPAN="6">제 45기 2015년 09월 30일 현재</TD></TR>'
        '<TR><TD COLSPAN="6">제 44기 2014년 12월 31일 현재</TD></TR>'
        '<TR><TD>회사명 : (주)특수건설</TD><TD COLSPAN="4"></TD><TD>(단위 : 원)</TD></TR>'
        '<TR><TD>계정명</TD><TD>주석</TD><TD COLSPAN="2">제 45(당)기</TD>'
        '<TD COLSPAN="2">제 44(전)기</TD></TR>'
        "<TR><TD>자산</TD><TD></TD><TD></TD><TD></TD><TD></TD><TD></TD></TR>"
        "<TR><TD>유동자산</TD><TD></TD><TD></TD><TD>100</TD><TD></TD><TD>90</TD></TR>"
        # 미착품류 — 당기(2열) 완전 공백, 전기 2열째만 값 존재.
        "<TR><TD>미착품</TD><TD></TD><TD></TD><TD></TD><TD></TD><TD>5</TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    cols = parse_header_columns(t)
    assert cols is not None
    ranks = {(c.position, c.period_rank, c.is_note) for c in cols}
    assert ranks == {(0, -1, True), (1, 0, False), (2, 0, False), (3, 1, False), (4, 1, False)}
    # 유동자산: 당기(position1|2)=100, 전기(position3|4)=90.
    assert select_by_header_columns(cols, [None, None, 100, None, 90]) == {0: 100, 1: 90}
    # 미착품: 당기 2열 전부 공백 → 당기는 결측(전기 5가 당기로 둔갑하면 안 됨).
    assert select_by_header_columns(cols, [None, None, None, None, 5]) == {1: 5}


def test_headerless_banner_rows_without_colgroup_still_falls_back():
    """`<COLGROUP>`이 없으면 배너/캡션행 판정 근거가 없어 R95 확장을 켜지 않는다
    (R6 원칙 — 모르면 기존 동작 그대로, 새 오탐 위험을 만들지 않는다)."""
    xml = (
        "<TABLE><TBODY>"
        '<TR><TD COLSPAN="6">재무상태표</TD></TR>'
        '<TR><TD>계정명</TD><TD>주석</TD><TD COLSPAN="2">제 45(당)기</TD>'
        '<TD COLSPAN="2">제 44(전)기</TD></TR>'
        "<TR><TD>유동자산</TD><TD></TD><TD></TD><TD>100</TD><TD></TD><TD>90</TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    assert parse_header_columns(t) is None


def test_headerless_full_width_blank_section_row_still_stops_scan():
    """`<COLGROUP>`이 있어도, 배너가 아니라 표 전체 폭을 채우는 진짜 섹션행("자산"
    류 — 물리 셀 수가 선언 열수와 같음)은 여전히 스캔을 멈추는 신호다(기존 R89
    안전장치 유지 — 배너행 건너뛰기가 이 판정을 무디게 만들면 안 됨)."""
    xml = (
        "<TABLE><COLGROUP><COL/><COL/><COL/></COLGROUP><TBODY>"
        "<TR><TD>자산</TD><TD></TD><TD></TD></TR>"
        "<TR><TD>매출액</TD><TD>100</TD><TD>90</TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    assert parse_header_columns(t) is None


def test_headerless_fully_blank_row_skipped_even_at_full_width():
    """R95 후속(2026-09-12, 손익계산서 표 재확인) — COLSPAN 병합이 아니라 개별 빈
    `<TD>`를 표 전체 폭만큼 나열한 **완전공백행**(라벨칸까지 빔)은 물리 셀 수가
    선언 열수와 같아 `is_banner` 판정을 피해가지만, 라벨 자체가 없어 "자산"류
    섹션행이 될 수 없다 — 무조건 건너뛰어야 진짜 헤더행에 도달한다. 실측: 00186939
    특수건설 20151116001903 포괄손익계산서(표제목 바로 다음 줄이 이 형태라 대손
    상각비/연구개발비 등 당기 결측 항목이 전기값으로 오적재되고 있었다)."""
    xml = (
        "<TABLE><COLGROUP><COL/><COL/><COL/><COL/><COL/></COLGROUP><TBODY>"
        '<TR><TD COLSPAN="5">포괄손익계산서</TD></TR>'
        "<TR><TD></TD><TD></TD><TD></TD><TD></TD><TD></TD></TR>"  # 완전공백행(5셀, 병합 없음)
        '<TR><TD COLSPAN="5">제45기2015년01월01일부터2015년09월30일까지</TD></TR>'
        '<TR><TD COLSPAN="5">제44기2014년01월01일부터2014년12월31일까지</TD></TR>'
        '<TR><TD>회사명 : (주)특수건설</TD><TD COLSPAN="3"></TD><TD>(단위 : 원)</TD></TR>'
        '<TR><TD>계정명</TD><TD COLSPAN="2">제 45(당)기 원화</TD>'
        '<TD COLSPAN="2">제 44(전)기 원화</TD></TR>'
        "<TR><TD>매출액</TD><TD></TD><TD>100</TD><TD></TD><TD>90</TD></TR>"
        # 대손상각비류 — 당기(2열) 완전 공백, 전기 2열째만 값 존재.
        "<TR><TD>대손상각비</TD><TD></TD><TD></TD><TD>5</TD><TD></TD></TR>"
        "</TBODY></TABLE>"
    )
    t = etree.fromstring(xml)
    cols = parse_header_columns(t)
    assert cols is not None
    ranks = {(c.position, c.period_rank) for c in cols}
    assert ranks == {(0, 0), (1, 0), (2, 1), (3, 1)}
    # 매출액: 당기(position1)=100, 전기(position3)=90.
    assert select_by_header_columns(cols, [None, 100, None, 90]) == {0: 100, 1: 90}
    # 대손상각비: 당기 2열 전부 공백 → 당기는 결측(전기 5가 당기로 둔갑하면 안 됨).
    assert select_by_header_columns(cols, [None, None, 5, None]) == {1: 5}


def test_ambiguous_duplicate_subtype_falls_back():
    """K-GAAP 구서식(2003년대) — "3개월"/"누적" 아래 다시 COLSPAN=2 하위열이 있는데
    텍스트가 둘 다 "금액"으로 동일해 헤더만으론 구분 불가(실측: 00132725 SB성보 2003Q3
    IS). 아무거나 고르면 조용히 틀린 값을 낼 위험 — 표 전체를 인식 실패로 보고 폴백."""
    thead = """
    <TR><TH ROWSPAN="3">구분</TH>
        <TH COLSPAN="4">제 43 기 반기</TH><TH COLSPAN="4">제 42 기 반기</TH></TR>
    <TR><TH COLSPAN="2">3개월</TH><TH COLSPAN="2">누적</TH>
        <TH COLSPAN="2">3개월</TH><TH COLSPAN="2">누적</TH></TR>
    <TR><TH COLSPAN="2">금액</TH><TH COLSPAN="2">금액</TH>
        <TH COLSPAN="2">금액</TH><TH COLSPAN="2">금액</TH></TR>
    """
    t = _table(thead, "<TR><TD>분기순이익</TD></TR>")
    assert parse_header_columns(t) is None


def test_select_by_header_columns_prefers_cumulative():
    """subtype 이 있는 그룹은 cumulative 만 채택 — 그 값이 None(원문 진짜 공란)이어도
    three_month 값으로 대체하지 않는다(R3/R85 원칙)."""
    thead = """
    <TR><TH ROWSPAN="2">　</TH><TH COLSPAN="2">제 57 기 반기</TH></TR>
    <TR><TH>3개월</TH><TH>누적</TH></TR>
    """
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert select_by_header_columns(cols, [100, 200]) == {0: 200}   # 누적(200) 채택
    assert select_by_header_columns(cols, [100, None]) == {}        # 누적 공란 → 3개월로 대체 안 함


def test_select_by_header_columns_merge_group_takes_single_nonnull():
    thead = """
    <TR><TH>과목</TH><TH COLSPAN="2">제 61 (당) 기</TH></TR>
    """
    t = _table(thead, "<TR><TD>가.당기순이익</TD></TR>")
    cols = parse_header_columns(t)
    assert select_by_header_columns(cols, [None, 500]) == {0: 500}
    assert select_by_header_columns(cols, [500, None]) == {0: 500}
    assert select_by_header_columns(cols, [None, None]) == {}       # 진짜 결측
    assert select_by_header_columns(cols, [500, 700]) == {}         # 판정 불가(R6) — 둘 다 값


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
