"""
표제기반 본문표 식별 회귀 테스트 (합성 XML, DB 비의존).

배경(Gate B iteration 5–6): 추출기 text.py 의 find_section_tables 전방수집이 복잡문서
(분할·기재정정)에서 본문 재무제표 대신 2차 조정표/요약표를 오연결했다(00259545: '3.정정사항'
요약표의 전기값 추출, 00111838: 0행). ⟹ 감사 reader 가 검증한 **표제기반 본문표 식별**을
추출기 1차 경로로 승격, 레거시 detect_sections 는 갭필 폴백으로만 사용.

검증:
  1) classify_statement_title: 본문 표제 인정 / 요약·주석·분할·자본변동 배제 / 기간마커 필수 / 연결·별도.
  2) _detect_body_statement_tables: TABLE-GROUP[표제, 데이터]에서 본문 데이터표만 선택, 정정·요약 배제.
  3) extract_facts 갭필: 표제기반이 BS 만 잡고 IS/CF 는 <P>헤더 레거시 폴백으로 채워지는지(섹션 손실 0).

실행: python fin2/tests/test_body_statement_tables.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.statement_titles import classify_statement_title  # noqa: E402
from fin2.extract.text import _detect_body_statement_tables, extract_facts  # noqa: E402


# ── 1) classify_statement_title 단위 ─────────────────────────────────────────

def test_classify_body_titles_accepted():
    assert classify_statement_title("연결 재무상태표 제68기 기말") == ("consolidated", "BS")
    assert classify_statement_title("포괄손익계산서 제10기 2022년") == ("separate", "IS")
    assert classify_statement_title("연결현금흐름표 제5기 현재") == ("consolidated", "CF")
    # 구형 대차대조표도 BS 로 인정
    assert classify_statement_title("대차대조표 제33기 기말")[1] == "BS"


def test_classify_excludes_summary_note_split_sce():
    # 요약·주석·분할·자본변동·정정요약 등은 본문 face 아님 → None
    assert classify_statement_title("3. 정정사항 요약 재무상태표 제31기") is None
    assert classify_statement_title("요약 연결재무상태표 제68기") is None
    assert classify_statement_title("연결 자본변동표 제5기 기말") is None
    assert classify_statement_title("주석 재무상태표 제3기") is None


def test_classify_rejects_note_sentence_mentions():
    # ★ statement 명을 문장 속에 언급한 주석표(천원 단위) 배제 → face ×1000 오염 방지(E1류).
    assert classify_statement_title(
        "당 기말 및 전기말 리스와 관련하여 연결재무상태표에 인식된 금액은 다음과 같습니다.") is None
    assert classify_statement_title(
        "22.1 당기말 및 전기말 현재 퇴직급여채무와 관련하여 재무상태표에 인식된 금액") is None
    assert classify_statement_title(
        "34. 금융상품의 공정가치당기말 및 전기말 현재 재무상태표에서 공정가치로") is None
    # 진짜 본문은 statement 명으로 시작 → 채택(enumerator·연결 접두 허용)
    assert classify_statement_title("연결 재무상태표 제 39 기 2022.12.31 현재 (단위 : 원)") == ("consolidated", "BS")
    assert classify_statement_title("1. 연결재무상태표 제39기 기말") == ("consolidated", "BS")
    assert classify_statement_title("분할 재무상태표 제3기") is None
    # ★ statement 명이 enumerator 뒤 문장 시작에 와도 한글 조사가 붙으면(="현금흐름표의 현금은…")
    # 표제 토큰이 아니라 문장 → 배제(삼천리자전거 CF 보충표 ×1000 오염 방지).
    assert classify_statement_title(
        "(1) 현금흐름표의 현금은 보고기간종료일 현재의 현금및현금성자산입니다.") is None
    assert classify_statement_title(
        "(2) 당기와 전기의 영업활동 현금흐름 중 조정과 순운전자본의 변동내역은 다음과 같습니다.") is None
    # 진짜 CF 본문은 statement 명이 단독 토큰 → 채택.
    assert classify_statement_title("현금흐름표 제 42 기 2020.01.01 부터 (단위 : 원)") == ("separate", "CF")
    # ★ 노트 섹션 제목 "NN. 현금흐름표(1) 현금흐름표의 현금은…현재…": 명칭 뒤가 "(1)"이라 기간마커가
    # 멀리 있으면 거부(동일기연 CF 보충표 ×1000 오염 방지). 본문은 명칭 직후 기간마커.
    assert classify_statement_title(
        "24. 현금흐름표(1) 현금흐름표의 현금은 보고기간종료일 현재의 현금및현금성자산입니다.") is None
    assert classify_statement_title(
        "재무상태표 상 자산 당기말 전기말 당기손익-공정가치측정금융자산 27,158,859") is None
    # ★ 명칭 직후 기간마커 변형: 제N(당)기말·당기말·날짜·(단위 모두 채택.
    assert classify_statement_title("재무상태표 제 32(당) 기말 2025년 12월 31일 현재 (단위 : 원)") == ("separate", "BS")
    assert classify_statement_title("재무상태표 당기말 전기말 (단위:천원)") == ("separate", "BS")
    assert classify_statement_title("재무상태표 2022.12.31 현재") == ("separate", "BS")


def test_classify_requires_period_marker():
    # 기간마커(제N기/기말/현재/날짜)가 없으면 일반표·헤더로 보고 배제
    assert classify_statement_title("연결 재무상태표") is None
    assert classify_statement_title("재무상태표에 표시되는 자산은") is None


# ── 2) _detect_body_statement_tables: 본문표만 선택, 정정·요약 배제 ───────────

_GROUP_XML = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 재무상태표 제68기 기말 (단위: 백만원)</TD></TR></TABLE>
   <TABLE><TR><TD>과목</TD><TD>당기</TD></TR>
          <TR><TD>자산총계</TD><TD>75,907</TD></TR>
          <TR><TD>유동부채</TD><TD>182,000</TD></TR></TABLE>
  </TABLE-GROUP>
  <TABLE-GROUP>
   <TABLE><TR><TD>3. 정정사항 요약 재무상태표 제31기</TD></TR></TABLE>
   <TABLE><TR><TD>유동부채</TD><TD>175,700</TD></TR></TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""


def test_body_table_selected_summary_excluded():
    root = etree.fromstring(_GROUP_XML.encode("utf-8"))
    groups = _detect_body_statement_tables(root, fin_type="A")
    assert set(groups) == {"BS_C"}, f"본문 BS 만 선택돼야 함: {set(groups)}"
    tbls = groups["BS_C"]
    assert len(tbls) == 1
    tbl, unit = tbls[0]
    txt = "".join(tbl.itertext())
    # 정정 요약표(175,700)가 아니라 본문 데이터표(182,000)가 선택돼야 한다(00259545 수정).
    assert "182,000" in txt and "175,700" not in txt
    assert unit == 1_000_000, f"표제 '단위: 백만원' 인식 실패: {unit}"


def test_fin_type_b_skips_consolidated():
    root = etree.fromstring(_GROUP_XML.encode("utf-8"))
    groups = _detect_body_statement_tables(root, fin_type="B")
    assert groups == {}, "연결 없는 기업(B)은 연결 표 무시"


# ── 3) extract_facts 갭필: 표제기반 BS + <P>헤더 IS/CF 폴백 ───────────────────

# BS 는 표제(기간마커 有)로 1차 식별, IS/CF 는 <P>헤더(기간마커 無)라 표제기반이 놓침
# → 레거시 detect_sections(_detect_sections_from_paragraphs) 갭필이 채워야 한다.
_GAPFILL_XML = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 재무상태표 제5기 기말</TD></TR></TABLE>
   <TABLE><TR><TD>자산총계</TD><TD>75,907</TD></TR></TABLE>
  </TABLE-GROUP>
  <P>연 결 포 괄 손 익 계 산 서</P>
  <TABLE><TR><TD>영업수익</TD><TD>1,234,567</TD></TR></TABLE>
  <P>연 결 현 금 흐 름 표</P>
  <TABLE><TR><TD>영업활동현금흐름</TD><TD>7,654,321</TD></TR></TABLE>
 </SECTION-2>
</DOCUMENT>"""


def _extract_from(xml: str):
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(xml)
        path = f.name
    try:
        return extract_facts(
            path, rcept_no="R", corp_code="C",
            report_fiscal_year=2023, report_fiscal_period="FY",
        )
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_facts_gapfill_covers_all_sections():
    facts = _extract_from(_GAPFILL_XML)
    # fs_type 은 source_ref 접두("BS_C/...")에 들어있다.
    sections = {(f.source_ref or "").split("/")[0] for f in facts}
    # BS=표제기반, IS·CF=<P>헤더 레거시 갭필 → 세 섹션 모두 추출돼야 한다(섹션 손실 0).
    assert "BS_C" in sections, f"표제기반 BS 누락: {sections}"
    assert "IS_C" in sections, f"갭필 IS 누락: {sections}"
    assert "CF_C" in sections, f"갭필 CF 누락: {sections}"


def test_extract_facts_excludes_correction_summary():
    # 본문 face 의 유동부채(182,000)만 추출되고 정정 요약(175,700)은 들어오면 안 된다.
    facts = _extract_from(_GROUP_XML)
    amounts = {f.amount_won for f in facts}
    assert 182_000_000_000 in amounts, "본문 유동부채(182,000 백만) 누락"
    assert 175_700_000_000 not in amounts, "정정 요약값(175,700)이 오추출됨"


if __name__ == "__main__":
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
    sys.exit(1 if failed else 0)
