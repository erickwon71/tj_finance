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
    parse_header_columns, select_by_header_columns, extract_rows, HeaderColumn,
    drop_mismatched_granularity_columns,
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


def test_two_tier_three_month_cumulative_letter_spaced_emphasis():
    """R111(2026-09-13, 2015+ IS_separate 항목수 분포 이상치 조사 중 발견) — 파워넷
    (00231354) 20150515001597 실측: 서브타입 헤더가 글자당 공백을 넣는 옛 강조체
    ("3 개 월", "누  적")를 쓴다. 옛 정규식(`3\\s*개월`은 "3"-"개월" 사이만 허용)이
    매칭 못 해 subtype=None으로 남고, 결국 당기 인터림 값(당기누적) 대신 엉뚱한
    비교연도(FY) 열이 "당기"로 잘못 채택됨(83.6억 대신 25.8억이 진짜 당기값). "3 개
    월"/"누  적"도 "3개월"/"누적"과 동일하게 subtype이 잡혀야 한다."""
    thead = """
    <TR>
      <TH ROWSPAN="2">　</TH>
      <TH COLSPAN="2">제 23 기 1분기</TH>
      <TH COLSPAN="2">제 22 기 1분기</TH>
      <TH>제 22 기</TH>
      <TH>제 21 기</TH>
    </TR>
    <TR><TH>3 개 월</TH><TH>누  적</TH><TH>3 개 월</TH><TH>누  적</TH></TR>
    """
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    got = [(c.position, c.period_rank, c.subtype) for c in cols]
    assert got[0] == (0, 0, "three_month")
    assert got[1] == (1, 0, "cumulative")
    assert got[2] == (2, 1, "three_month")
    assert got[3] == (3, 1, "cumulative")
    # 당기(period_rank=0)는 누적(position1)이 채택돼야 한다 — FY 비교열(position4/5)이
    # 아니라.
    assert select_by_header_columns(cols, [25_781_758_600, 25_781_758_600,
                                            15_775_073_821, 15_775_073_821,
                                            82_662_901_775, 71_058_982_667]) == {
        0: 25_781_758_600, 1: 15_775_073_821, 2: 82_662_901_775, 3: 71_058_982_667,
    }


def test_note_column_header_letter_spaced_emphasis_still_recognized():
    """R112(2026-09-13, CF_separate 항목수 분포 이상치 조사 중 발견) — 한양증권
    (00162416) 20160329000677 실측: 주석 컬럼 헤더가 글자당 공백을 넣는 옛 강조체
    ("주  석")를 써서 옛 정확매치("주석" in text)가 실패 → 주석번호("35")가 진짜
    금액 열처럼 취급돼 "나.당기순이익에 대한 조정" 등에 엉뚱한 "35" 행이 추가로
    끼어들었다. "주  석"도 "주석"과 동일하게 is_note=True 여야 한다."""
    thead = """
    <TR><TH>과목</TH><TH>주  석</TH><TH>제 61(당) 기</TH><TH>제 60(전) 기</TH></TR>
    """
    t = _table(thead, "<TR><TD>나.당기순이익에 대한 조정</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert cols[0].is_note is True and cols[0].position == 0
    assert [(c.position, c.period_rank) for c in cols[1:]] == [(1, 0), (2, 1)]
    # 주석번호("35")가 당기금액으로 오채택되면 안 된다.
    assert select_by_header_columns(cols, ["35", -4_501_035_344, -3_553_499_276]) == {
        0: -4_501_035_344, 1: -3_553_499_276,
    }


def test_dash_only_cell_treated_as_zero_not_missing():
    """R113(2026-09-13, 사용자 원문대조로 발견) — 자비스(전 아이비케이에스제5호기업
    인수목적) 01174038 20170811000259 CF 별도 실측: "Ⅱ.투자활동"/"Ⅲ.재무활동" 원문이
    둘 다 "-"(대시)인데(=이 카테고리 활동 없음, 결측 아님 — 사용자 확인: "-를 0으로
    표현하는 것이 맞는 구조") `parse_amount("-")→None`이라 두 행이 통째로 유실됐다
    (전수확인: CF에서 "투자활동" 라벨 자체가 없는 rcept×basis 2,127건/전체 285,861건).
    순수 대시 칸은 raw_amounts로 구분해 0으로 채택해야 한다."""
    cols = [HeaderColumn(position=0, period_key="제2(당)기 반기", period_rank=0, subtype=None),
            HeaderColumn(position=1, period_key="제2(당)기 반기", period_rank=0, subtype=None)]
    # 실측 그대로: position0="　"(공란, 진짜 결측) / position1="-"(대시, =0).
    assert select_by_header_columns(cols, [None, None], raw_amounts=["", "-"]) == {0: 0}
    # raw_amounts 안 넘기면(기존 호출자) 회귀 없이 그대로 결측 유지.
    assert select_by_header_columns(cols, [None, None]) == {}
    # 진짜 값이 있으면 대시 판정보다 우선(정상 케이스, 회귀 없음).
    assert select_by_header_columns(cols, [None, 5], raw_amounts=["", "5"]) == {0: 5}


def test_dash_only_cell_zero_with_subtype_columns():
    """R113 — 3개월/누적 서브타입 헤더에서도 순수 대시는 0으로 채택돼야 한다."""
    cols = [HeaderColumn(position=0, period_key="제57기 반기", period_rank=0, subtype="three_month"),
            HeaderColumn(position=1, period_key="제57기 반기", period_rank=0, subtype="cumulative")]
    assert select_by_header_columns(cols, [100, None], raw_amounts=["100", "-"]) == {0: 0}


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


def test_merge_group_no_subtype_dash_placeholder_column_not_ambiguous():
    """R114(2026-09-14, 케이엠제약 20160516000811 IS/CF 별도 원문대조로 발견) — R113
    직후 회귀. SPAC 합병 첫 사업연도 표는 "제1(당)기" 하나가 COLSPAN=2 로 물리열 2개를
    덮는데(subtype 구분 텍스트 없음), 그중 **한 열 전체가 구조적으로 순수 대시**고
    실제 값은 나머지 한 열에만 있다("영업비용" 열1="-" 열2="(21,402,210)"). R113 이
    대시 열도 0으로 채택해버리면 두 열 다 "값 있음"이 돼 R6 판정불가로 행 전체가
    유실됐다(실측: IS 별도 11행 중 9행, CF 별도도 동형 붕괴). 대시 열은 "값 있음"
    판정에서 제외하고 진짜 값 하나만 골라야 한다."""
    thead = """
    <TR><TH>과목</TH><TH COLSPAN="2">제 1(당) 기</TH></TR>
    """
    t = _table(thead, "<TR><TD>영업비용</TD></TR>")
    cols = parse_header_columns(t)
    # position0=대시(구조적 placeholder) / position1=진짜 당기금액.
    assert select_by_header_columns(
        cols, [None, -21_402_210], raw_amounts=["-", "(21,402,210)"]
    ) == {0: -21_402_210}
    # 두 열 다 대시뿐(예: "영업수익")이면 구조적 0 — R113 취지 그대로 유지.
    assert select_by_header_columns(cols, [None, None], raw_amounts=["-", "-"]) == {0: 0}
    # 한 열은 대시, 한 열은 완전공란(넥슨게임즈 "기초 현금및현금성자산" 실측 패턴)
    # — 대시 증거가 하나라도 있고 나머지가 공란뿐이면 마찬가지로 구조적 0.
    assert select_by_header_columns(cols, [None, None], raw_amounts=["", "-"]) == {0: 0}
    # 진짜 값이 2개면(대시 아닌 값 2개) 여전히 판정불가(R6) — 회귀 없음.
    assert select_by_header_columns(
        cols, [500, 700], raw_amounts=["500", "700"]
    ) == {}


def test_r115_drop_annual_reference_columns_from_interim_report():
    """R115(2026-09-14, 형지I&C 20160516001490·드림시큐리티 20160511001294 실측) —
    분기보고서 IS 표가 자사 분기 열("제41기 1분기" 3개월/누적) 뒤에 분기/반기 접미사
    없는 순수 연도서수 참고열("제40기"·"제39기")을 추가로 붙이는 서식. "제40기 1분기"
    (rank1)와 "제40기"(rank2)는 같은 회계연도인데 물리적으로 다른 rank 를 받아,
    위치기반 `context_fiscal_year = report_fiscal_year - col_index` 공식이 rank2 를
    엉뚱한 연도로 계산해버린다(실측: 2016년 보고서에서 rank2 가 2015 대신 2014로
    계산됨) — 진짜 실적행이 전부 이 rank 로 밀려나 소실됐다. 분기·반기 보고서에서는
    이 참고열을 통째로 배제하고 남은 rank 를 0부터 재부여해야 한다."""
    thead = """
    <TR><TH ROWSPAN="2">과목</TH>
        <TH COLSPAN="2">제 41 기 1분기</TH>
        <TH COLSPAN="2">제 40 기 1분기</TH>
        <TH ROWSPAN="2">제 40 기</TH>
        <TH ROWSPAN="2">제 39 기</TH></TR>
    <TR><TH>3개월</TH><TH>누적</TH><TH>3개월</TH><TH>누적</TH></TR>
    """
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert [(c.period_key, c.period_rank) for c in cols] == [
        ("제 41 기 1분기", 0), ("제 41 기 1분기", 0),
        ("제 40 기 1분기", 1), ("제 40 기 1분기", 1),
        ("제 40 기", 2), ("제 39 기", 3),
    ]
    filtered = drop_mismatched_granularity_columns(cols, "Q1")
    assert [(c.period_key, c.period_rank) for c in filtered] == [
        ("제 41 기 1분기", 0), ("제 41 기 1분기", 0),
        ("제 40 기 1분기", 1), ("제 40 기 1분기", 1),
    ]   # 순수 연도서수 열("제 40 기"·"제 39 기") 배제, 남은 rank 0/1 은 gap 없이 유지
    # 누적 열(포지션1/3)에 실적값이 있으면 이제 정확히 rank0/1 로 채택된다(예전엔
    # 배제 전인 rank2/3 자리의 "제 40 기"/"제 39 기" 값이 엉뚱한 연도로 함께 살아
    # 있었다 — 필터 후에는 그 두 열 자체가 애초에 없다).
    assert select_by_header_columns(filtered, [None, 100, None, 200, 999, 888]) == {
        0: 100, 1: 200,
    }


def test_r115_fy_report_untouched():
    """FY 보고서는 애초에 전부 순수 연도서수 열이라 R115 필터가 아무것도 지우지
    않아야 한다(조기반환)."""
    thead = '<TR><TH>과목</TH><TH>제 41 기</TH><TH>제 40 기</TH></TR>'
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert drop_mismatched_granularity_columns(cols, "FY") == cols


def test_r115_all_bare_annual_falls_back_to_original():
    """분기 보고서인데도 표 전체가 순수 연도서수 열뿐이면(예: 구형 K-GAAP 서식) 다
    지워 표 전체가 유실되면 안 된다 — 원본 그대로 폴백(R6, 모르면 확장하지 않는다)."""
    thead = '<TR><TH>과목</TH><TH>제 43 기</TH><TH>제 42 기</TH></TR>'
    t = _table(thead, "<TR><TD>매출액</TD></TR>")
    cols = parse_header_columns(t)
    assert drop_mismatched_granularity_columns(cols, "Q3") == cols


def test_r116_q1_cumulative_blank_uses_three_month_when_allowed():
    """R116(2026-09-14, 사용자 원문대조로 확정) — 형지I&C 20160516001490 실측: Q1
    보고서인데 "누적" 칸이 통째로 공란이고 "3개월" 칸만 채워져 있다("당기순이익"
    행만 예외적으로 둘 다 채워 두 값이 동일함을 필자 스스로 증명). 예외목록으로
    허용된 필링에서만 누적 공란 시 3개월 값을 대체 채택한다."""
    cols = [HeaderColumn(position=0, period_key="제 41 기 1분기", period_rank=0, subtype="three_month"),
            HeaderColumn(position=1, period_key="제 41 기 1분기", period_rank=0, subtype="cumulative")]
    # 허용 안 하면(기존 호출자, 기본값) 여전히 대체 안 함 — 회귀 없음.
    assert select_by_header_columns(cols, [100, None]) == {}
    # 허용하면 누적 공란 시 3개월 값을 채택.
    assert select_by_header_columns(
        cols, [100, None], allow_three_month_as_cumulative=True,
    ) == {0: 100}
    # 누적 값이 실제로 있으면 여전히 누적이 우선(대체 발동 안 함).
    assert select_by_header_columns(
        cols, [100, 200], allow_three_month_as_cumulative=True,
    ) == {0: 200}


def test_r116_merge_group_duplicate_equal_values_accepted_when_allowed():
    """R116 — 드림시큐리티 20160511001294 실측: 서브타입 구분 텍스트가 없는 병합군
    (R114 else 분기)인데 두 물리열이 **완전히 같은 값**을 중복 기재했다(3개월=누적
    등식을 필자가 그대로 두 칸에 반복).

    ★R131(2026-09-16) 후속 — KD 20200515002825 실측으로, 이 "값 동일" 판정은
    `allow_three_month_as_cumulative` 예외 플래그와 무관하게(모호함이 없으므로)
    **항상** 채택하도록 일반화됐다 — 아래 첫 assert 가 옛 회귀 기대값({})에서
    새 기대값({0: 100})으로 바뀐 이유. 값이 서로 다르면(진짜 판정불가) 여전히
    건너뛴다(플래그 유무 무관, R6 유지)."""
    cols = [HeaderColumn(position=0, period_key="제 3 기 1분기", period_rank=0, subtype=None),
            HeaderColumn(position=1, period_key="제 3 기 1분기", period_rank=0, subtype=None)]
    # R131 — 플래그 없어도(기본 호출자) 값이 같으면 이제 채택한다.
    assert select_by_header_columns(cols, [100, 100]) == {0: 100}
    # 플래그를 켜도 동일하게 채택(회귀 없음).
    assert select_by_header_columns(
        cols, [100, 100], allow_three_month_as_cumulative=True,
    ) == {0: 100}
    # 값이 서로 다르면(진짜 판정불가) 플래그 유무와 무관하게 여전히 건너뜀.
    assert select_by_header_columns(cols, [100, 200]) == {}
    assert select_by_header_columns(
        cols, [100, 200], allow_three_month_as_cumulative=True,
    ) == {}


def test_r117_blank_note_header_column_does_not_abort_whole_table():
    """R117(2026-09-14, 아주IB투자 20150817001086 CF 연결 실측) — 주석번호 참조열인데
    헤더 셀 자체가 완전공란(`<TH/>` 자기닫힘, "주석"이라는 글자조차 없음)인 서식.
    기존엔 "기간패턴도 주석표시도 없는 열"로 보고 표 전체를 폴백시켜(구버전 cum_map/
    multicol/else 경로), CF 본체(영업/투자/재무활동현금흐름 등)가 통째로 유실됐다
    (실측: 32행 중 30행). 헤더 스택이 완전공란이면 주석열과 동일하게 is_note=True 로
    건너뛰어야 한다."""
    thead = """
    <TR><TH>과목</TH><TH></TH>
        <TH COLSPAN="2">제 42 기 반기</TH>
        <TH COLSPAN="2">제 41 기 반기</TH></TR>
    """
    t = _table(thead, "<TR><TD>영업활동으로인한현금흐름</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert cols[0].is_note is True and cols[0].position == 0   # 완전공란 열
    assert [(c.position, c.period_rank) for c in cols[1:]] == [(1, 0), (2, 0), (3, 1), (4, 1)]


def test_r119_subtype_suffix_in_same_cell_as_period_recognized():
    """R119(2026-09-14, 푸른저축은행 20150213000097 IS 별도 실측) — THEAD 없는 구서식은
    헤더가 한 줄뿐이라 서브타입 표시가 별도 스택행이 아니라 같은 셀 안에서 기간 텍스트
    바로 뒤 괄호로 붙는다("제 45기 반기(3개월)"/"제 45기 반기(누적)"). 매치된 셀
    자신의 잔여 텍스트도 subtype 판정에 포함시켜야 한다 — 안 그러면 두 물리열 다
    subtype=None 이 돼(둘 다 "값 있음") R6 판정불가로 행 전체가 유실된다."""
    thead = """
    <TR><TH>계정과목</TH>
        <TH>제 45기 반기(3개월)</TH><TH>제 45기 반기(누적)</TH>
        <TH>제 44기 반기(3개월)</TH><TH>제 44기 반기(누적)</TH></TR>
    """
    t = _table(thead, "<TR><TD>영업수익</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert [(c.position, c.period_rank, c.subtype) for c in cols] == [
        (0, 0, "three_month"), (1, 0, "cumulative"),
        (2, 1, "three_month"), (3, 1, "cumulative"),
    ]
    # 누적이 우선 채택되고, 두 값이 서로 달라도(3개월≠누적, H1의 정상 형태) 판정불가로
    # 떨어지지 않는다.
    assert select_by_header_columns(cols, [12_154_137_521, 43_070_181_646, None, None]) == {
        0: 43_070_181_646,
    }


def test_r120_headerless_merge_group_prefers_last_position_when_allowed():
    """R120(2026-09-14, 사용자 확정 — "예외목록으로만 좁힐") — 웹케시 20180814001946,
    우리기술투자 20200813000621 실측: H1 보고서 IS 표가 같은 라벨을 구분 텍스트 없이
    물리적으로 다른 2열에 반복하는데 두 열 다 실제 값이고 서로 다르다(3개월≠누적).
    산수 검증(Q1값 + 1번째열 = 2번째열)으로 확정된 DART 관행([3개월,누적] 순서)을
    예외목록 필링에서만 적용 — 위치상 마지막 열(누적)을 채택한다."""
    cols = [HeaderColumn(position=0, period_key="제 20 기 반기", period_rank=0, subtype=None),
            HeaderColumn(position=1, period_key="제 20 기 반기", period_rank=0, subtype=None)]
    # 허용 안 하면(기본값) 서로 다른 값 2개는 여전히 판정불가(R6) — 회귀 없음.
    assert select_by_header_columns(cols, [100, 200]) == {}
    # 허용하면 마지막 열(누적) 채택.
    assert select_by_header_columns(
        cols, [100, 200], prefer_last_of_two_as_cumulative=True,
    ) == {0: 200}
    # 열이 3개 이상인 병합군에는 적용 안 함(2열 한정).
    cols3 = [HeaderColumn(position=0, period_key="제 20 기", period_rank=0, subtype=None),
             HeaderColumn(position=1, period_key="제 20 기", period_rank=0, subtype=None),
             HeaderColumn(position=2, period_key="제 20 기", period_rank=0, subtype=None)]
    assert select_by_header_columns(
        cols3, [100, 200, 300], prefer_last_of_two_as_cumulative=True,
    ) == {}


def test_r122_missing_gi_after_parenthetical_still_recognized():
    """R122(2026-09-14, 레이크머티리얼즈 20180813000607·케이엠제약 20170814000310·
    자비스 20180515000191 등 CF 별도 저조 이상치 스크리닝 중 발견) — "제N(당)기 반기"
    류 표기에서 괄호 바로 뒤 "기"를 빠뜨리고 "제N(당) 반기"로 적는 오타가 서로 무관한
    최소 3개 회사에 걸쳐 반복 확인됐다(같은 회계 소프트웨어/템플릿을 쓰는 소형사 군의
    공통 결함으로 추정). "기"가 빠져도 뒤따르는 "반기"/"N분기" 자체가 이미 기간을
    명확히 하므로 인정해야 한다."""
    thead = "<TR><TH>과목</TH><TH>제2(당) 반기</TH><TH>제2(당) 반기</TH></TR>"
    t = _table(thead, "<TR><TD>영업활동현금흐름</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert [(c.position, c.period_rank) for c in cols] == [(0, 0), (1, 0)]

    thead_q = "<TR><TH>과목</TH><TH>제3(당) 1분기</TH><TH>제2(전) 1분기</TH></TR>"
    t2 = _table(thead_q, "<TR><TD>영업활동현금흐름</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert [(c.position, c.period_rank) for c in cols2] == [(0, 0), (1, 1)]

    # 정상 표기("기" 있음)도 여전히 인식(회귀 없음).
    thead_ok = "<TR><TH>과목</TH><TH>제2(당)기 반기</TH></TR>"
    t3 = _table(thead_ok, "<TR><TD>영업활동현금흐름</TD></TR>")
    cols3 = parse_header_columns(t3)
    assert cols3 is not None and cols3[0].period_rank == 0


def test_r123_securities_firm_accounting_year_and_relative_quarter_labels():
    """R123(2026-09-15, 2015+ 전수 폴백 스캔으로 발견) — 증권사류가 흔히 쓰는 4가지
    변형 헤더가 전부 인식돼야 한다."""
    # ① "2015회계연도 1분 기"(제 접두 없음, 연도+회계연도, 글자당 공백).
    t1 = _table("<TR><TH>과목</TH><TH>2015회계연도 1분 기</TH><TH>2014회계연도</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols1 = parse_header_columns(t1)
    assert cols1 is not None
    assert [c.period_rank for c in cols1] == [0, 1]

    # ② 제 접두 누락("11기 1분기" — 첫 열은 정상 "제 12기 1분기").
    t2 = _table("<TR><TH>과목</TH><TH>제 12기 1분기</TH><TH>11기 1분기</TH></TR>",
                "<TR><TD>영업활동현금흐름</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert [c.period_rank for c in cols2] == [0, 1]

    # ③ 서수 없는 "분기"("제 16(당) 분기말" — "N분기"가 아니라 "분기"만).
    t3 = _table("<TR><TH>과목</TH><TH>제 16(당) 분기말</TH><TH>제 15(전) 기말</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols3 = parse_header_columns(t3)
    assert cols3 is not None
    assert [c.period_rank for c in cols3] == [0, 1]

    # ④ 서수 자체가 없는 상대어 합성("당분기말"/"전기말" — NH투자증권류).
    t4 = _table("<TR><TH>과목</TH><TH>당분기말</TH><TH>전기말</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols4 = parse_header_columns(t4)
    assert cols4 is not None
    assert [c.period_rank for c in cols4] == [0, 1]

    # 회귀 없음 — 기존 "당기"/"전기" 단독 표기도 여전히 인식.
    t5 = _table("<TR><TH>과목</TH><TH>당기</TH><TH>전기</TH></TR>",
                "<TR><TD>당기순이익</TD></TR>")
    cols5 = parse_header_columns(t5)
    assert cols5 is not None
    assert [c.period_rank for c in cols5] == [0, 1]


def test_r125_duplicate_subtype_columns_gated_off_by_default():
    """R125(2026-09-15, 현대해상·다올투자증권·대신증권 등 2015+ 폴백 스캔 후속) — "3개월"/
    "누적" 아래 COLSPAN=2 하위열이 명세행(1열)/소계행(2열)로 고정된 2015+ 보험/증권사
    서식(실측: 현대해상 20150817001369 IS 별도). 기본값(allow_duplicate_subtype=False,
    기존 호출자)은 여전히 표 전체 폴백 — SB성보(2003, pre-2015 K-GAAP)가 이 규칙에
    안 맞아 조용히 틀린 값을 냈던 실측 회귀(R124 최초 시도, `test_hyphen_negative_gate_
    r31.py::test_cum_map_misalignment_fixed_by_gate_widening`) 때문에 report_lines.py
    가 report_fiscal_year>=2015 일 때만 True 로 넘기도록 스코프를 좁힌다."""
    thead = """
    <TR><TH ROWSPAN="3">구분</TH>
        <TH COLSPAN="4">제 62 기 (당) 반기</TH></TR>
    <TR><TH COLSPAN="2">3개월</TH><TH COLSPAN="2">누적</TH></TR>
    <TR><TH>명세</TH><TH>소계</TH><TH>명세</TH><TH>소계</TH></TR>
    """
    t = _table(thead, "<TR><TD>가.보험영업수익</TD></TR>")
    # 기본값(False, 기존 회귀 없음) — 표 전체 폴백.
    assert parse_header_columns(t) is None
    # allow_duplicate_subtype=True(2015+ 전용 게이트) — 헤더 파싱 성공.
    cols = parse_header_columns(t, allow_duplicate_subtype=True)
    assert cols is not None
    assert [c.subtype for c in cols] == ["three_month", "three_month",
                                          "cumulative", "cumulative"]
    # 명세행: 3개월 1열(명세)에만 실값 → 채택. 소계행: 3개월 2열(소계)에만 실값 → 채택.
    assert select_by_header_columns(cols, [100, None, 300, None]) == {0: 300}
    assert select_by_header_columns(cols, [None, 200, None, 400]) == {0: 400}
    # 두 열 다 실값이면(진짜 판정불가) 여전히 건너뜀 — 짐작 금지 원칙 유지.
    assert select_by_header_columns(cols, [None, None, 300, 350]) == {}


def test_r126_bare_calendar_date_recognized_as_period_key():
    """R126(2026-09-15, R123+R125 적용 후 잔여 72건 재조사) — "제N기" 서수 체계를
    아예 안 쓰고 달력 날짜로만 기간을 표기하는 회사들(신라젠 등) 실측."""
    # ① "YYYY.MM.DD"(점 구분, 서수 없음) — 신라젠 20150601000841 BS 별도.
    t1 = _table("<TR><TH>과목</TH><TH>2015.03.31</TH><TH>2014.12.31</TH></TR>",
                "<TR><TD>유동자산</TD></TR>")
    cols1 = parse_header_columns(t1)
    assert cols1 is not None
    assert [c.period_rank for c in cols1] == [0, 1]

    # ② "YYYY-MM-DD"(하이픈 구분) — FSN 20150515000348 BS 별도.
    t2 = _table("<TR><TH>과목</TH><TH>2015-03-31</TH></TR>", "<TR><TD>유동자산</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None and cols2[0].period_rank == 0

    # ③ "YYYY년 NQ"(연도+영문분기) — FSN 20150515000348 IS/CF 별도.
    t3 = _table("<TR><TH>과목</TH><TH>2015년 1Q</TH></TR>", "<TR><TD>영업수익</TD></TR>")
    cols3 = parse_header_columns(t3)
    assert cols3 is not None and cols3[0].period_key == "2015년 1Q"

    # ④ "YYYY년[...]"(월/말/반기 접미 옵션) — 우리금융지주 20190515002466 BS 연결.
    for text in ("2018년", "2018년 12월", "2018년말", "2018년 반기"):
        t = _table(f"<TR><TH>과목</TH><TH>제1(당)기 1분기</TH><TH>{text}</TH></TR>",
                   "<TR><TD>자산총계</TD></TR>")
        cols = parse_header_columns(t)
        assert cols is not None, text
        assert [c.period_rank for c in cols] == [0, 1], text

    # ⑤ "YYYY년"(서수 없는 3개년 비교) — 티로보틱스 20180402000209 BS/IS 별도.
    t5 = _table("<TR><TH>과목</TH><TH>2017년</TH><TH>2016년</TH><TH>2015년</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols5 = parse_header_columns(t5)
    assert cols5 is not None
    assert [c.period_rank for c in cols5] == [0, 1, 2]


def test_r128b_two_digit_year_quarter_recognized_and_not_confused_with_four_digit():
    """R128b(2026-09-15, 이노시뮬레이션 20191129001722 CF 연결 실측, NO THEAD) —
    "19년 3분기"/"18년 3분기"(연도 2자리 축약형+N분기) 헤더가 인식 안 돼 "3분기"만
    매치되고 당기/전기가 같은 rank 로 병합됐다(수정 전 73행 중 71행 유실)."""
    t = _table("<TR><TH>계정과목</TH><TH>19년 3분기</TH><TH>18년 3분기</TH></TR>",
               "<TR><TD>영업활동현금흐름</TD></TR>")
    cols = parse_header_columns(t)
    assert cols is not None
    assert [c.period_rank for c in cols] == [0, 1]

    # 회귀 없음 — 4자리 연도(R126)가 2자리 브랜치에 잘못 가로채이면 안 된다.
    t2 = _table("<TR><TH>과목</TH><TH>제1(당)기 1분기</TH><TH>2018년 12월</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert cols2[-1].period_key == "2018년 12월", cols2


def test_r126_transition_or_establishment_date_column_treated_as_note():
    """R126(2026-09-15) — "전환일"(IFRS 최초채택 3번째 비교재무상태표 기준일)·"설립일
    현재"(신규상장사가 전기 대신 넣는 기준일) 열은 회계기간이 아니라 참고용 고정
    기준일이다. 진짜 "제N(당)기"/"제N(전)기" 열은 그대로 인식되고, 이 열만 is_note
    로 건너뛴다(실측: 롤링스톤 20160330002986 BS 별도 등 8개사)."""
    t = _table(
        "<TR><TH>과목</TH><TH>제 7(당) 기</TH><TH>제 6(전) 기</TH>"
        "<TH>전 환 일(감사받지 않은 재무제표)</TH></TR>",
        "<TR><TD>자산총계</TD></TR>",
    )
    cols = parse_header_columns(t)
    assert cols is not None
    assert [(c.period_rank, c.is_note) for c in cols] == [(0, False), (1, False), (-1, True)]

    # "설립일 현재(...)" 변형도 동일하게 처리(패션플랫폼류).
    t2 = _table("<TR><TH>과목</TH><TH>제1(당)기 3분기말</TH><TH>설립일 현재</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert [(c.period_rank, c.is_note) for c in cols2] == [(0, False), (-1, True)]


def test_r126_missing_opening_paren_typo_recognized():
    """R126(2026-09-15) — "제N(당)기"류 표기에서 여는 괄호만 빠뜨리는 오타("제20전)기"
    처럼 닫는 괄호는 있는데 여는 괄호가 없음)가 최소 4개 무관한 회사(삼성화재해상보험·
    보라티알·듀켐바이오·키움증권)에서 반복 확인됐다. R122(닫는 괄호 뒤 "기" 탈락)의
    거울상 오타."""
    # 키움증권 20200330004481 CF 별도: "제21(당)기 제20전)기".
    t1 = _table("<TR><TH>과목</TH><TH>제21(당)기</TH><TH>제20전)기</TH></TR>",
                "<TR><TD>영업활동현금흐름</TD></TR>")
    cols1 = parse_header_columns(t1)
    assert cols1 is not None
    assert [c.period_rank for c in cols1] == [0, 1]

    # 듀켐바이오 20200330001256 IS 연결: "제 17당) 기 제 16(전) 기 제 15(전전) 기".
    t2 = _table(
        "<TR><TH>과목</TH><TH>제 17당) 기</TH><TH>제 16(전) 기</TH><TH>제 15(전전) 기</TH></TR>",
        "<TR><TD>매출액</TD></TR>",
    )
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert [c.period_rank for c in cols2] == [0, 1, 2]

    # 회귀 없음 — 정상 표기("(당)"/"(전)" 둘 다 괄호 있음)도 여전히 인식.
    t3 = _table("<TR><TH>과목</TH><TH>제5(당)기</TH><TH>제4(전)기</TH></TR>",
                "<TR><TD>매출액</TD></TR>")
    cols3 = parse_header_columns(t3)
    assert cols3 is not None
    assert [c.period_rank for c in cols3] == [0, 1]


def test_r128_relative_term_with_digit_quarter_not_merged_into_bare_ordinal():
    """R128(2026-09-15, 4개 이상치 카테고리 재검증 중 발견) — "당N분기"/"전N분기"
    (상대어+숫자+분기, 바이오솔루션 20161114001893 IS 별도 실측: "당3분기"/"전3분기")
    가 서수 브랜치("제" 접두 옵션 허용, R123)에 "당"/"전" 접두어를 무시당하고 그냥
    "3분기"만 매치돼 두 물리적으로 다른 기간이 같은 rank 로 병합되던 결함. 수정 전엔
    당3분기·전3분기 둘 다 period_key="3분기" 로 같은 rank(0)에 겹쳐 R6 판정불가로
    행 대부분(28개 중 25개)이 유실됐다."""
    t = _table(
        "<TR><TH>과목</TH><TH>주석</TH>"
        "<TH COLSPAN=\"2\">당3분기</TH><TH COLSPAN=\"2\">전3분기(검토받지 않은 재무제표)</TH></TR>"
        "<TR><TH>3개월</TH><TH>누 적</TH><TH>3개월</TH><TH>누 적</TH></TR>",
        "<TR><TD>매출액</TD></TR>",
    )
    cols = parse_header_columns(t)
    assert cols is not None
    # 라벨열(과목) + 주석열(is_note) 다음 4개 실데이터 열 — 당3분기 2개(rank0), 전3분기
    # 2개(rank1)로 반드시 분리돼야 한다(수정 전엔 전부 rank0 하나로 뭉개졌다).
    real_cols = [c for c in cols if not c.is_note]
    assert [c.period_rank for c in real_cols] == [0, 0, 1, 1], cols
    assert real_cols[0].period_key != real_cols[2].period_key, \
        "당3분기/전3분기가 같은 period_key 로 뭉개지면 안 됨"

    # 회귀 없음 — 서수 없는 "당분기"/"전분기"(R123)와 "제N(당)기"류(R111~)는 그대로 인식.
    t2 = _table("<TR><TH>과목</TH><TH>당분기말</TH><TH>전기말</TH></TR>",
                "<TR><TD>자산총계</TD></TR>")
    cols2 = parse_header_columns(t2)
    assert cols2 is not None
    assert [c.period_rank for c in cols2] == [0, 1]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
