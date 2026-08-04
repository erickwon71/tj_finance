"""구형 레이아웃(`XI. 재무제표 등`) 본문표 식별 회귀 테스트 (합성 XML, DB 비의존).

배경 — 2015+ 계층2 적재 공백 189건 중 **109건이 본문 섹션(`2.연결재무제표`/`4.재무제표`)이
아예 없는 구형 서식**이었다(2026-08-04 전수 원문 파싱). 이 서식은 재무제표와 주석이
`XI. 재무제표 등` **한 섹션에 같이** 살아서, 섹션 경계가 본문을 보장해주지 못한다.

⚠ 이 테스트가 지키는 것은 **주석 오염 차단**이다. 2023년 DB손해보험 사고(앵커 없는 폴백이
   천원단위 주석표를 본문으로 집어 이익잉여금 8.5경원 적재)와 같은 구조의 위험이라,
   느슨해지는 방향의 변경은 여기서 실패해야 한다.

실행: python -m pytest fin2/tests/test_legacy_layout_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.statement_titles import (  # noqa: E402
    classify_legacy_statement_heading, is_legacy_note_marker,
)
from fin2.extract.text import _detect_body_statement_tables  # noqa: E402


# ── 1) 헤딩 분류기 단위 ──────────────────────────────────────────────────────

def test_accepts_inline_period_heading():
    """A형(73건) — 표제에 기간이 인라인된 제목표. 실측 20141128001023."""
    assert classify_legacy_statement_heading(
        "연결 재무상태표 제 30 기 반기말 2014.09.30 현재 (단위 : 원)"
    ) == ("consolidated", "BS")
    assert classify_legacy_statement_heading(
        "재무상태표 제 30 기 반기말 2014.09.30 현재 (단위 : 원)"
    ) == ("separate", "BS")


def test_accepts_bare_spaced_heading():
    """B형(14건) — 명칭만 있는 <P> 헤딩(자간 벌림). 기간은 다음 형제 표에 있다.
    실측 20141128000231 메이슨캐피탈."""
    assert classify_legacy_statement_heading(
        "반 기 연 결 재 무 상 태 표") == ("consolidated", "BS")
    assert classify_legacy_statement_heading(
        "반 기 연 결 포 괄 손 익 계 산 서") == ("consolidated", "IS")
    assert classify_legacy_statement_heading("현금흐름표") == ("separate", "CF")


def test_rejects_numbered_note_heading():
    """★핵심 회귀 — 주석 헤딩도 재무제표명으로 시작한다('29. 현금흐름표').
    번호 접두로 가른다. 이게 뚫리면 뒤따르는 주석표가 본문 CF 가 된다."""
    assert classify_legacy_statement_heading("29. 현금흐름표") is None
    assert classify_legacy_statement_heading("27. 현금흐름표 (연결)") is None
    assert classify_legacy_statement_heading("1) 재무상태표") is None
    assert classify_legacy_statement_heading("Ⅲ. 포괄손익계산서") is None


def test_rejects_sentence_mentions():
    """주석 문장 속 재무제표명 — 시작 앵커와 '명칭 직후 기간마커' 로 배제."""
    assert classify_legacy_statement_heading(
        "현금흐름표의 현금은 재무상태표상의 현금및현금성자산입니다.") is None
    assert classify_legacy_statement_heading(
        "리스와 관련하여 연결재무상태표에 인식된 금액은 다음과 같습니다.") is None
    assert classify_legacy_statement_heading(
        "재무상태표상 자산으로 인식된 금액") is None


def test_rejects_summary_and_note_titles():
    assert classify_legacy_statement_heading("요약연결재무상태표") is None
    assert classify_legacy_statement_heading("연결재무제표에 대한 주석") is None
    assert classify_legacy_statement_heading("분할재무상태표 제30기 기말") is None
    assert classify_legacy_statement_heading("연결재무상태표 명세서 제30기 기말") is None


def test_sce_is_opt_in():
    """자본변동표는 기본 배제(fact_v2/std_v2 순이익 오염 방지), 계층2 만 opt-in."""
    t = "연결 자본변동표 제 30 기 반기 2014.04.01 부터"
    assert classify_legacy_statement_heading(t) is None
    assert classify_legacy_statement_heading(t, include_sce=True) == ("consolidated", "SCE")


def test_note_marker_detection():
    assert is_legacy_note_marker("연결재무제표에 대한 주석")
    assert is_legacy_note_marker("별도재무제표에 대한 주석")
    assert not is_legacy_note_marker("별첨 주석은 본 반기연결재무제표의 일부입니다.")
    assert not is_legacy_note_marker("연결 재무상태표 제 30 기 반기말")


# ── 2) 감지기 통합(합성 XML) ─────────────────────────────────────────────────

def _data_table(*rows: tuple[str, str]) -> str:
    trs = "".join(
        f"<TR><TD><P>{label}</P></TD><TD><P>{amount}</P></TD></TR>"
        for label, amount in rows
    )
    return f"<TABLE>{trs}</TABLE>"


LEGACY_DOC = f"""<DOCUMENT>
 <SECTION-1><TITLE>III. 재무에 관한 사항</TITLE></SECTION-1>
 <SECTION-2><TITLE>XI. 재무제표 등</TITLE>
   <TABLE><TR><TD><P>연결 재무상태표 제 30 기 기말 2014.09.30 현재 (단위 : 원)</P></TD></TR></TABLE>
   {_data_table(('자산총계', '1,111,111,111'), ('부채총계', '222,222,222'))}
   <TABLE><TR><TD><P>연결 포괄손익계산서 제 30 기 2014.09.30 (단위 : 원)</P></TD></TR></TABLE>
   {_data_table(('매출액', '3,333,333,333'), ('영업이익', '444,444,444'))}
   <P>연결재무제표에 대한 주석</P>
   <P>29. 현금흐름표</P>
   {_data_table(('영업으로부터창출된현금', '999,999,999'), ('이자수취', '111,222,333'))}
   <P>10. 유형자산</P>
   {_data_table(('토지', '888,888,888'), ('건물', '444,555,666'))}
   <TABLE><TR><TD><P>재무상태표 제 30 기 기말 2014.09.30 현재 (단위 : 원)</P></TD></TR></TABLE>
   {_data_table(('자산총계', '555,555,555'), ('부채총계', '123,456,789'))}
   <P>별도재무제표에 대한 주석</P>
   {_data_table(('주석표행', '777,777,777'), ('주석표행2', '321,321,321'))}
 </SECTION-2>
 <SECTION-2><TITLE>XII. 부속명세서</TITLE>
   {_data_table(('부속명세행', '666,666,666'), ('부속명세행2', '654,654,654'))}
 </SECTION-2>
</DOCUMENT>"""


def _amounts(groups, code):
    """그 섹션코드로 잡힌 표들의 금액 셀 원문 집합."""
    out = set()
    for tbl, _unit, _kind in groups.get(code, []):
        out.update(t.strip() for t in tbl.itertext() if "," in t)
    return out


def test_legacy_detector_finds_body_and_skips_notes():
    root = etree.fromstring(LEGACY_DOC.encode())
    groups = _detect_body_statement_tables(root, fin_type="A", include_sce=True)

    assert "1,111,111,111" in _amounts(groups, "BS_C")
    assert "3,333,333,333" in _amounts(groups, "IS_C")
    assert "555,555,555" in _amounts(groups, "BS_S")

    # ★ 주석 구간의 표는 어느 섹션에도 들어가면 안 된다.
    picked = {a for code in groups for a in _amounts(groups, code)}
    assert "999,999,999" not in picked, "'29. 현금흐름표' 주석표가 CF 본문으로 샜다"
    assert "888,888,888" not in picked, "유형자산 주석표가 본문으로 샜다"
    assert "777,777,777" not in picked, "별도 주석표가 본문으로 샜다"
    # 다음 섹션(부속명세서)으로 넘어가지 않는다.
    assert "666,666,666" not in picked


def test_legacy_fallback_respects_fin_type_b():
    """연결을 만들지 않는 기업(FIN_TYPE=B)에는 연결 표를 만들지 않는다(2015+ 경로와 동일)."""
    root = etree.fromstring(LEGACY_DOC.encode())
    groups = _detect_body_statement_tables(root, fin_type="B", include_sce=True)
    assert not any(code.endswith("_C") for code in groups)
    assert "555,555,555" in _amounts(groups, "BS_S")


MODERN_DOC = f"""<DOCUMENT>
 <SECTION-2><TITLE>2. 연결재무제표</TITLE>
   <TABLE><TR><TD><P>연결 재무상태표 제 10 기 기말 (단위 : 원)</P></TD></TR></TABLE>
   {_data_table(('자산총계', '1,000,000,000'), ('부채총계', '250,000,000'))}
 </SECTION-2>
 <SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>
   <P>29. 현금흐름표</P>
   {_data_table(('영업으로부터창출된현금', '999,999,999'), ('이자수취', '111,222,333'))}
 </SECTION-2>
</DOCUMENT>"""


def test_modern_layout_unaffected():
    """본문 섹션이 있으면 구형 폴백은 발동하지 않는다 — 기존 102,067건 무영향의 근거.
    (실측으로도 확인: 적재분 600건 표본에서 폴백 발동 0건)"""
    root = etree.fromstring(MODERN_DOC.encode())
    groups = _detect_body_statement_tables(root, fin_type="A", include_sce=True)
    assert "1,000,000,000" in _amounts(groups, "BS_C")
    picked = {a for code in groups for a in _amounts(groups, code)}
    assert "999,999,999" not in picked


def test_no_legacy_section_returns_empty():
    """구형 섹션도 본문 섹션도 없으면 빈 dict — 추측으로 채우지 않는다(R6)."""
    doc = ("<DOCUMENT><SECTION-2><TITLE>II. 사업의 내용</TITLE>"
           + _data_table(("생산능력", "1,234,567"), ("가동률", "2,345,678"))
           + "</SECTION-2></DOCUMENT>")
    root = etree.fromstring(doc.encode())
    assert _detect_body_statement_tables(root, fin_type="A", include_sce=True) == {}
