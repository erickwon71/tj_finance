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
