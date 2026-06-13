"""
<P> 헤더 기반 재무제표 섹션 탐지 회귀 테스트 (합성 XML, 파일·DB 비의존).

배경(item 4): 보험·증권·지주·SPAC 등 레거시 ACODE 보고서는 재무제표 표제가 <TITLE> 이
아니라 <P>연결재무상태표</P> 처럼 데이터 TABLE 과 같은 SECTION 의 직계 형제 <P> 로 존재.
TITLE 만 스캔하던 detect_sections 가 이를 놓치고 주석표를 오매칭 → 추출 0행이었다.

검증:
  1) <P> 표제로 BS/IS/CF(연결·별도) 섹션을 정확히 탐지.
  2) find_section_tables 가 다음 표제 <P> 전까지 형제 데이터 TABLE 만 수집(섹션 경계).
  3) 주석/요약/번호접두 표제("(1) 부문별 요약 재무상태표","33. 현금흐름표")는 배제.

실행: python -m fin2.tests.test_section_p_header
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from parser.xml.section_detector import (  # noqa: E402
    detect_sections, find_section_tables, _is_statement_header, _EXCLUDE_PATTERNS,
)

# 금융사 레이아웃 모사: 컨테이너 TITLE + <P> 표제 + 데이터 TABLE 형제들.
# 주석 오매칭 함정도 포함: "(1) 부문별 요약 재무상태표", "33. 현금흐름표".
_XML = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <P>연 결 재 무 상 태 표</P>
  <TABLE><TR><TD>제68기 기말</TD></TR></TABLE>
  <TABLE><TR><TD>자산총계</TD><TD>75,907</TD></TR><TR><TD>부채총계</TD><TD>63,979</TD></TR></TABLE>
  <P>연 결 포 괄 손 익 계 산 서</P>
  <TABLE><TR><TD>영업수익</TD><TD>100</TD></TR></TABLE>
  <P>(1) 부문별 요약 재무상태표</P>
  <TABLE><TR><TD>함정주석</TD><TD>1</TD></TR></TABLE>
  <P>연 결 현 금 흐 름 표</P>
  <TABLE><TR><TD>영업활동현금흐름</TD><TD>5</TD></TR></TABLE>
 </SECTION-2>
 <SECTION-2>
  <TITLE>4. 재무제표</TITLE>
  <P>재 무 상 태 표</P>
  <TABLE><TR><TD>자산총계</TD><TD>70,000</TD></TR></TABLE>
  <P>33. 현금흐름표</P>
  <TABLE><TR><TD>주석함정</TD><TD>9</TD></TR></TABLE>
 </SECTION-2>
</DOCUMENT>"""


def _root():
    return etree.fromstring(_XML.encode("utf-8"))


def test_consolidated_sections_detected():
    s = detect_sections(_root())
    assert s["BS_C"] is not None, "연결 BS 표제 <P> 미탐지"
    assert s["IS_C"] is not None, "연결 IS 표제 <P> 미탐지"
    assert s["CF_C"] is not None, "연결 CF 표제 <P> 미탐지"


def test_separate_bs_detected_not_note():
    s = detect_sections(_root())
    # 별도 BS = "재 무 상 태 표"(연결 제외), 주석 "(1)부문별 요약"이 아님
    assert s["BS_S"] is not None
    txt = "".join(s["BS_S"].itertext()).replace(" ", "")
    assert "부문" not in txt and "요약" not in txt


def test_section_tables_bounded_by_next_header():
    s = detect_sections(_root())
    tables = find_section_tables(s["BS_C"])
    # BS_C 는 기간헤더+데이터 2표만(다음 표제 <P>연결포괄손익...> 전까지)
    assert len(tables) == 2, f"기대 2표, 실제 {len(tables)}"
    joined = "".join("".join(t.itertext()) for t in tables)
    assert "자산총계" in joined and "영업수익" not in joined


def test_note_headers_rejected():
    excl_bs = _EXCLUDE_PATTERNS.get("BS_S", [])
    # 주석/요약/번호접두는 표제 아님
    assert not _is_statement_header("(1) 부문별 요약 재무상태표", ["재무상태표"], excl_bs)
    assert not _is_statement_header("33. 현금흐름표", ["현금흐름표"], [])
    # 긴 주석 문장도 배제
    assert not _is_statement_header(
        "재무상태표에 표시되는 금융자산 총액 및 상계된 금융부채", ["재무상태표"], excl_bs)
    # 진짜 표제는 통과(공백·정상)
    assert _is_statement_header("연 결 재 무 상 태 표", ["연결", "재무상태표"], [])
    assert _is_statement_header("현금흐름표", ["현금흐름표"], [])


def test_multi_note_ref_column_not_parsed_as_amount():
    """금융업 다중 주석참조('2,4,32,34,35,36')가 금액으로 오인되어 컬럼이 밀리지 않아야 함.

    배경: _split_label_amounts 가 쉼표 제거 후 주석 판정 → '2,4,32,…'→'243234…' 가
    금액과 혼동되어 col0 을 차지, 실제 당기값이 col1 로 밀림(부국증권 H1 매출=전년값).
    """
    from parser.xml.table_extractor import _split_label_amounts
    cells = ["Ⅰ. 현금 및 예치금", "2,4,32,34,35,36",
             "496,412,633,753", "125,529,986,707", "148,432,981,080"]
    label, amounts = _split_label_amounts(cells)
    assert label.startswith("Ⅰ. 현금")
    # 주석참조는 제외 → 금액 3개만, 당기=496,412,633,753 가 첫 금액
    assert len(amounts) == 3, f"기대 금액 3개, 실제 {len(amounts)}: {amounts}"
    assert amounts[0].replace(",", "") == "496412633753"
    # 정상 3자리그룹 소액("2,433")은 주석 아님 → 금액으로 유지
    _, amt2 = _split_label_amounts(["기타", "2,433", "1,000"])
    assert amt2 and amt2[0].replace(",", "") == "2433"
    # 단일 주석번호("34")는 여전히 제외
    _, amt3 = _split_label_amounts(["자산", "34", "1,000,000"])
    assert amt3 and amt3[0].replace(",", "") == "1000000"


def test_interim_is_cumulative_table_wins_over_annual_comparative():
    """금융업 interim IS: [3개월|누적] 반기표가 [전기|전전기] 연간비교표보다 먼저 처리되어
    당기누적값이 col0 을 선점해야 함(연간비교표의 전년 FY값 오염 차단).

    부국증권 H1 매출이 2017 FY값(566B)으로 오염되던 버그의 합성 회귀.
    """
    from fin2.extract.text import extract_facts
    xml = """<DOCUMENT><SECTION-2>
      <TITLE>2. 연결재무제표</TITLE>
      <P>연 결 포 괄 손 익 계 산 서</P>
      <TABLE>
        <TR><TD>과목</TD><TD>주석</TD><TD>제65(당)반기</TD><TD></TD><TD>제64(전)반기</TD><TD></TD></TR>
        <TR><TD></TD><TD></TD><TD>3개월</TD><TD>누적</TD><TD>3개월</TD><TD>누적</TD></TR>
        <TR><TD>Ⅰ. 영업수익</TD><TD>37</TD><TD>144,000,000,000</TD><TD>314,000,000,000</TD><TD>161,000,000,000</TD><TD>324,000,000,000</TD></TR>
        <TR><TD>Ⅷ. 반기순이익</TD><TD>37</TD><TD>8,000,000,000</TD><TD>20,000,000,000</TD><TD>13,000,000,000</TD><TD>28,000,000,000</TD></TR>
      </TABLE>
      <TABLE>
        <TR><TD>과목</TD><TD>주석</TD><TD>제64(전)기</TD><TD>제63(전전)기</TD></TR>
        <TR><TD>Ⅰ. 영업수익</TD><TD>37</TD><TD>566,000,000,000</TD><TD>753,000,000,000</TD></TR>
        <TR><TD>Ⅷ. 당기순이익</TD><TD>37</TD><TD>37,000,000,000</TD><TD>27,000,000,000</TD></TR>
      </TABLE>
      <P>연 결 현 금 흐 름 표</P>
      <TABLE><TR><TD>영업활동현금흐름</TD><TD>5</TD></TR></TABLE>
    </SECTION-2></DOCUMENT>"""
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as fh:
        fh.write(xml)
        path = fh.name
    try:
        facts = extract_facts(path, rcept_no="T", corp_code="T",
                              report_fiscal_year=2018, report_fiscal_period="H1")
    finally:
        os.unlink(path)
    rev0 = [f.amount_won for f in facts
            if f.canonical_account == "is.revenue" and f.basis == "consolidated"
            and f.col_index == 0]
    assert rev0, "영업수익 col0 미추출"
    # 당기누적 314B 가 선점, 연간비교표 566B 오염 아님
    assert 314_000_000_000 in rev0, f"기대 314B(당기누적), 실제 {rev0}"
    assert 566_000_000_000 not in rev0, f"연간비교 566B 오염: {rev0}"
    # 순이익: 계정명이 달라(반기순이익 vs 당기순이익) dedup 로 못 막으므로 연간비교표
    # 자체를 스킵해야 함. 당기누적 20B 만, 연간비교 37B 오염 없어야.
    ni0 = [f.amount_won for f in facts
           if f.canonical_account == "is.net_income" and f.basis == "consolidated"
           and f.col_index == 0]
    assert 20_000_000_000 in ni0, f"기대 20B(반기순이익 누적), 실제 {ni0}"
    assert 37_000_000_000 not in ni0, f"연간비교 37B(당기순이익) 오염: {ni0}"


def test_sce_changes_in_equity_not_absorbed_into_is():
    """자본변동표(SCE)가 포괄손익계산서 바로 뒤 <P> 로 올 때, IS 표 수집이 SCE 에서
    멈춰야 함. 안 그러면 SCE 의 '연결당기순이익' 행이 is.net_income 을 오염(Q1 순이익
    =SCE 전년값). FY 단일컬럼 보고서 모사.
    """
    from fin2.extract.text import extract_facts
    xml = """<DOCUMENT><SECTION-2>
      <TITLE>2. 연결재무제표</TITLE>
      <P>연 결 포 괄 손 익 계 산 서</P>
      <TABLE>
        <TR><TD>과목</TD><TD>주석</TD><TD>제65(당)기</TD></TR>
        <TR><TD>Ⅰ. 영업수익</TD><TD>37</TD><TD>100,000,000,000</TD></TR>
        <TR><TD>Ⅷ. 당기순이익</TD><TD>37</TD><TD>11,000,000,000</TD></TR>
      </TABLE>
      <P>연 결 자 본 변 동 표</P>
      <TABLE>
        <TR><TD>과목</TD><TD>자본금</TD><TD>이익잉여금</TD><TD>총계</TD></TR>
        <TR><TD>5. 연결당기순이익</TD><TD></TD><TD>27,000,000,000</TD><TD>27,000,000,000</TD></TR>
      </TABLE>
      <P>연 결 현 금 흐 름 표</P>
      <TABLE><TR><TD>영업활동현금흐름</TD><TD>5</TD></TR></TABLE>
    </SECTION-2></DOCUMENT>"""
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as fh:
        fh.write(xml)
        path = fh.name
    try:
        facts = extract_facts(path, rcept_no="T", corp_code="T",
                              report_fiscal_year=2018, report_fiscal_period="FY")
    finally:
        os.unlink(path)
    ni = [f.amount_won for f in facts
          if f.canonical_account == "is.net_income" and f.basis == "consolidated"]
    assert 11_000_000_000 in ni, f"IS 당기순이익 미추출: {ni}"
    assert 27_000_000_000 not in ni, f"SCE 연결당기순이익 27B 오염: {ni}"


def test_numbered_inline_period_header_accepted():
    """소·중형사 레이아웃: 번호접두+기간 인라인 표제("1)재무상태표(대차대조표)제33기…")를
    표제로 인식. 단, 기간마커 없는 주석 제목("21.현금흐름표 당사는…")은 거부(=오매칭 방지).
    """
    from parser.xml.section_detector import _is_statement_header, _EXCLUDE_PATTERNS
    excl_bs = _EXCLUDE_PATTERNS.get("BS_S", [])
    # 진짜 표제(번호접두 + 기간 인라인) → 인식
    assert _is_statement_header(
        "1)재무상태표(대차대조표)제33기 2022년 12월 31일 현재 제32기 2021년", ["재무상태표"], excl_bs)
    assert _is_statement_header(
        "5)현금흐름표 제33기 2022년 1월 1일부터 2022년 12월 31일까지", ["현금흐름표"], [])
    # 연결 수식어 + 번호 + 기간 → 연결 표제 인식
    assert _is_statement_header(
        "1)연결재무상태표 제33기 2022년 12월 31일 현재", ["연결", "재무상태표"], [])
    # 주석 제목(번호접두지만 기간마커 없음) → 거부
    assert not _is_statement_header(
        "21.현금흐름표 당사는 간접법에 의하여 현금흐름표를 작성하고 있으며", ["현금흐름표"], [])
    # 표제명이 문장 중간(주석 서술) → 거부
    assert not _is_statement_header(
        "당사는 현금흐름표를 제33기부터 간접법으로 작성", ["현금흐름표"], [])


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
