"""pre-2015(K-GAAP 구서식, ≤2010) 계층2 2차 패스 본문표 식별 회귀 테스트 (합성 XML, DB 비의존).

배경 — Phase2 설계문서(`docs/plans/pre2015_layer2_backfill_phase2_design_2026-08-10.md`)가
원문 실측으로 확정한 근본원인: `assign_tables_to_dart_sections`/`iter_section_elements`
는 중첩 SECTION-N 하위표제("가.대차대조표")를 만나면 최상위 매치가 이미 성공했어도 **즉시
리셋**한다 — 1999~2008 실측 0%. `fin2.extract.legacy_pre2015`(이 파일이 지키는 대상)는
깊이인식 경계walk 로 이를 우회하되, **2015+ 소비 경로는 한 줄도 건드리지 않는다**(회귀
방지가 Phase3 완료 조건).

★ 이 테스트가 지키는 두 가지:
  1. **중첩 하위표제를 통과한다** — 최상위 섹션 매치 이후 "가./나./다." 를 만나도 리셋되지
     않고 그 안의 데이터표를 계속 찾는다(근본원인 재발 방지).
  2. **주석 오염 차단은 여전히 유효하다** — 병합 레거시 테스트(`test_legacy_layout_tables.py`)
     와 같은 원칙, 다른 구조(분리형 SEC_SEP_FS/SEC_CONSOL_FS)에서도 지켜야 한다.

실행: python -m pytest fin2/tests/test_pre2015_legacy_layout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.legacy_pre2015 import (  # noqa: E402
    classify_pre2015_statement_heading, detect_pre2015_body_statement_tables,
    detect_squished_bs_total_assets, iter_section_span_depth_aware,
)


# ── 1) 헤딩 분류기 단위 ──────────────────────────────────────────────────────

def test_accepts_ordinal_prefixed_heading():
    """K-GAAP 실측 형태 — 한글서수 하위표제("가./나./다.")."""
    assert classify_pre2015_statement_heading("가. 대차대조표") == ("separate", "BS")
    assert classify_pre2015_statement_heading("나.손익계산서") == ("separate", "IS")
    assert classify_pre2015_statement_heading("라. 현금흐름표") == ("separate", "CF")
    assert classify_pre2015_statement_heading("가. 연결대차대조표") == ("consolidated", "BS")


def test_accepts_kgaap_appropriation_tables():
    """사용자 결정 Q1(포함) — 이익잉여금처분계산서/결손금처리계산서 → APPR."""
    assert classify_pre2015_statement_heading("다. 이익잉여금처분계산서") == ("separate", "APPR")
    assert classify_pre2015_statement_heading("다. 결손금처리계산서") == ("separate", "APPR")


def test_still_accepts_inline_period_and_bare_heading():
    """기존 legacy 분류기가 지원하던 A형/B형 서식도 그대로 받는다(확장이지 대체가 아님)."""
    assert classify_pre2015_statement_heading(
        "연결 재무상태표 제 30 기 반기말 2014.09.30 현재 (단위 : 원)"
    ) == ("consolidated", "BS")
    assert classify_pre2015_statement_heading("현금흐름표") == ("separate", "CF")


def test_rejects_numbered_note_heading():
    """★핵심 회귀 — 주석 번호 헤딩('29. 현금흐름표')은 한글서수가 아니라 숫자 접두라 걸러진다."""
    assert classify_pre2015_statement_heading("29. 현금흐름표") is None
    assert classify_pre2015_statement_heading("Ⅲ. 포괄손익계산서") is None


def test_rejects_sentence_mentions_and_summary():
    assert classify_pre2015_statement_heading(
        "현금흐름표의 현금은 재무상태표상의 현금및현금성자산입니다.") is None
    assert classify_pre2015_statement_heading("요약연결재무상태표") is None
    assert classify_pre2015_statement_heading("연결재무제표에 대한 주석") is None


def test_sce_is_opt_in():
    t = "가. 연결자본변동표"
    assert classify_pre2015_statement_heading(t) is None
    assert classify_pre2015_statement_heading(t, include_sce=True) == ("consolidated", "SCE")


# ── 2) 감지기 통합(합성 XML) — 핵심 회귀: 중첩 SECTION 하위표제를 통과하는가 ─────────

def _data_table(*rows: tuple[str, str]) -> str:
    trs = "".join(
        f"<TR><TD><P>{label}</P></TD><TD><P>{amount}</P></TD></TR>"
        for label, amount in rows
    )
    return f"<TABLE>{trs}</TABLE>"


# 실측 구조(현대모비스 20000330000228 류) 재현 — SECTION-2 최상위 매치 성공 후
# SECTION-3 한글서수 하위표제가 **중첩**된다. 구파이프라인은 여기서 리셋돼 0% 였다.
# ★ 표제 뒤 기간마커(<P>제 N 기 … 현재 (단위 : 원)</P>)를 실측 서식대로 붙인다 — 계층2
# 헤딩판정은 SECTION-3 요소 자신의 **전체 서브트리 텍스트**(TITLE+뒤따르는 형제)를 후보로
# 보므로(iter_section_span_depth_aware 는 `iter_section_elements`처럼 개별 리프만 내지
# 않고 아직 안 끝난 섹션 자신도 낸다), 실제 DART 문서처럼 명칭 직후에 기간마커가 와야
# `classify_pre2015_statement_heading`의 '명칭 직후 마커' 조건이 통과한다(마커 없이 라벨만
# 있으면 문장 취급돼 거부된다 — 주석 오염 차단 조건 그대로).
_PERIOD_MARK = "<P>제 30 기 2010.12.31 현재 (단위 : 원)</P>"

NESTED_KGAAP_DOC = f"""<DOCUMENT>
 <SECTION-1><TITLE>3. 재무에 관한 사항</TITLE>
  <SECTION-2><TITLE>3. 재무제표</TITLE>
    <SECTION-3><TITLE>가. 대차대조표</TITLE>{_PERIOD_MARK}
      {_data_table(('자산총계', '1,111,111,111'), ('부채총계', '222,222,222'))}
    </SECTION-3>
    <SECTION-3><TITLE>나. 손익계산서</TITLE>{_PERIOD_MARK}
      {_data_table(('매출액', '3,333,333,333'), ('영업이익', '444,444,444'))}
    </SECTION-3>
    <SECTION-3><TITLE>다. 이익잉여금처분계산서</TITLE>{_PERIOD_MARK}
      {_data_table(('미처분이익잉여금', '9,999,999'), ('차기이월이익잉여금', '8,888,888'))}
    </SECTION-3>
    <SECTION-3><TITLE>라. 현금흐름표</TITLE>{_PERIOD_MARK}
      {_data_table(('영업활동현금흐름', '555,555,555'), ('투자활동현금흐름', '-66,666,666'))}
    </SECTION-3>
    <SECTION-3><TITLE>마. 재무제표에 대한 주석</TITLE>
      <P>29. 현금흐름표</P>
      {_data_table(('영업으로부터창출된현금', '999,999,999'), ('이자수취', '111,222,333'))}
      <P>10. 유형자산</P>
      {_data_table(('토지', '888,888,888'), ('건물', '444,555,666'))}
    </SECTION-3>
  </SECTION-2>
  <SECTION-2><TITLE>4. 연결재무제표</TITLE>
    <SECTION-3><TITLE>가. 연결대차대조표</TITLE>{_PERIOD_MARK}
      {_data_table(('자산총계', '7,777,777,777'), ('부채총계', '666,666,666'))}
    </SECTION-3>
  </SECTION-2>
 </SECTION-1>
</DOCUMENT>"""


def _amounts(groups, code):
    out = set()
    for tbl, _unit, _kind in groups.get(code, []):
        out.update(t.strip() for t in tbl.itertext() if "," in t)
    return out


def test_nested_subheading_no_longer_resets_span():
    """★근본원인 회귀 테스트 — 중첩 SECTION-3 하위표제를 통과해 4종 모두 잡는다."""
    root = etree.fromstring(NESTED_KGAAP_DOC.encode())
    groups = detect_pre2015_body_statement_tables(root, fin_type="A", include_sce=True)

    assert "1,111,111,111" in _amounts(groups, "BS_S")
    assert "3,333,333,333" in _amounts(groups, "IS_S")
    assert "555,555,555" in _amounts(groups, "CF_S")
    assert "9,999,999" in _amounts(groups, "APPR_S")
    assert "7,777,777,777" in _amounts(groups, "BS_C")


def test_note_section_still_excluded_inside_nested_structure():
    """주석 하위표제(마.) 안의 표는 어느 섹션에도 들어가면 안 된다 — 중첩 통과가 주석
    오염으로 이어지지 않는지가 핵심(2023년 DB손해보험류 사고와 같은 위험 형태)."""
    root = etree.fromstring(NESTED_KGAAP_DOC.encode())
    groups = detect_pre2015_body_statement_tables(root, fin_type="A", include_sce=True)
    picked = {a for code in groups for a in _amounts(groups, code)}
    assert "999,999,999" not in picked, "'29. 현금흐름표' 주석표가 CF 본문으로 샜다"
    assert "888,888,888" not in picked, "유형자산 주석표가 본문으로 샜다"


def test_fin_type_b_skips_consolidated_section_entirely():
    """연결을 만들지 않는 기업은 연결 섹션 자체를 훑지 않는다(2015+ 경로와 동일 규약)."""
    root = etree.fromstring(NESTED_KGAAP_DOC.encode())
    groups = detect_pre2015_body_statement_tables(root, fin_type="B", include_sce=True)
    assert not any(code.endswith("_C") for code in groups)
    assert "1,111,111,111" in _amounts(groups, "BS_S")


def test_sibling_section_change_still_ends_span():
    """형제-이하 레벨의 진짜 섹션 전환(다음 SECTION-2)에서는 여전히 구간이 끝난다 —
    깊이인식이 '전혀 리셋 안 함'으로 퇴화하지 않았는지 확인."""
    doc = f"""<DOCUMENT>
     <SECTION-2><TITLE>3. 재무제표</TITLE>
       <SECTION-3><TITLE>가. 대차대조표</TITLE>
         {_data_table(('자산총계', '1,000,000,000'))}
       </SECTION-3>
     </SECTION-2>
     <SECTION-2><TITLE>6. 기타 재무에 관한 사항</TITLE>
       {_data_table(('부속명세행', '999,000,000'))}
     </SECTION-2>
    </DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    elements = iter_section_span_depth_aware(root, "재무제표")
    texts = {" ".join("".join(el.itertext()).split()) for _, el in elements}
    assert not any("999,000,000" in t for t in texts), "다음 SECTION-2 로 구간이 새어나갔다"


def test_basis_comes_from_section_not_heading_text():
    """연결 섹션 안의 하위표제가 '연결' 접두 없이 나와도(Phase1 미확인 사항) 섹션이
    basis 를 보장한다 — 표제 문구의 basis 를 신뢰하지 않는다(모듈 docstring 근거)."""
    doc = f"""<DOCUMENT>
     <SECTION-2><TITLE>4. 연결재무제표</TITLE>
       <SECTION-3><TITLE>가. 대차대조표</TITLE>{_PERIOD_MARK}
         {_data_table(('자산총계', '5,000,000,000'), ('부채총계', '1,000,000,000'))}
       </SECTION-3>
     </SECTION-2>
    </DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    groups = detect_pre2015_body_statement_tables(root, fin_type="A", include_sce=True)
    assert "5,000,000,000" in _amounts(groups, "BS_C")
    assert "5,000,000,000" not in _amounts(groups, "BS_S")


def test_no_body_section_returns_empty():
    """분리형 섹션 자체가 없으면(구조가 다른 문서) 빈 dict — 추측으로 채우지 않는다(R6)."""
    doc = ("<DOCUMENT><SECTION-2><TITLE>II. 사업의 내용</TITLE>"
           + _data_table(("생산능력", "1,234,567"))
           + "</SECTION-2></DOCUMENT>")
    root = etree.fromstring(doc.encode())
    assert detect_pre2015_body_statement_tables(root, fin_type="A", include_sce=True) == {}


# ── 3) (A-3, 2026-09-05) 통짜-셀 BS 표 — total_assets 한정 안전 복구 ──────────────
# 설계문서: docs/plans/category_c_a3_squished_cell_bs_total_assets_design_2026-09-05.md
# 실측 원문(호텔신라 20050915000066·한국팩키지 20040528000335·삼표시멘트
# 20051214000337) 구조를 재현 — 표 하나가 물리적으로 TR 1개(헤더 TH행 + 데이터
# TD행 1개)뿐이고, 라벨/금액이 각각 줄바꿈 없이 셀 하나에 통짜로 이어붙는다.

def _squished_table(label_blob: str, *value_blobs: str) -> str:
    """실측 구조 재현 — TR0(TH 헤더, TD 아님)+TR1(TD 라벨열+TD 값열들)."""
    header_cells = "".join("<TH>제N기</TH>" for _ in value_blobs)
    value_cells = "".join(f"<TD>{v}</TD>" for v in value_blobs)
    return (f"<TABLE><TR><TH>과목</TH>{header_cells}</TR>"
            f"<TR><TD>{label_blob}</TD>{value_cells}</TR></TABLE>")


SQUISHED_BS_DOC = f"""<DOCUMENT>
 <SECTION-2><TITLE>4. 재무제표</TITLE>
   <SECTION-3><TITLE>가. 대차대조표</TITLE>
     <TABLE-GROUP>대 차 대 조 표</TABLE-GROUP>
     <TABLE><TR><TD>제 30 기 2010.12.31 현재</TD></TR>
            <TR><TD>제 29 기 2009.12.31 현재</TD></TR>
            <TR><TD>(단위 : 원)</TD></TR></TABLE>
     {_squished_table(
         "자      산  Ⅰ. 유동자산   1. 현금  2. 매출채권자산총계   부      채  Ⅰ.유동부채"
         "   1.매입채무부채총계   자      본  Ⅰ.자본금자본총계부채와자본총계",
         "500,000,000300,000,000200,000,0001,000,000,000600,000,000600,000,000"
         "400,000,000400,000,0001,000,000,000",
         "450,000,000280,000,000170,000,000900,000,000550,000,000550,000,000"
         "350,000,000350,000,000900,000,000",
     )}
   </SECTION-3>
   <SECTION-3><TITLE>나. 손익계산서</TITLE>{_PERIOD_MARK}
     {_data_table(('매출액', '9,999,999'))}
   </SECTION-3>
 </SECTION-2>
</DOCUMENT>"""


def test_squished_bs_recovers_total_assets_from_last_token():
    """핵심 회귀 — 개별 항목 정렬 없이 '부채와자본총계=자산총계' 항등식으로 마지막
    숫자 토큰만 취해도 정확한 값을 복구한다(§design doc §1-4)."""
    root = etree.fromstring(SQUISHED_BS_DOC.encode())
    out = detect_squished_bs_total_assets(root, fin_type="B")
    assert "BS_S" in out
    value, unit_hint = out["BS_S"]
    assert value == 1_000_000_000  # 당기(컬럼0) 마지막 토큰


def test_squished_bs_rejects_label_tail_not_total():
    """라벨 꼬리가 '총계'로 안 끝나면(구조 확신 없음) 조용히 거부 — 추측하지 않는다."""
    doc = f"""<DOCUMENT>
     <SECTION-2><TITLE>4. 재무제표</TITLE>
       <SECTION-3><TITLE>가. 대차대조표</TITLE>
         <TABLE-GROUP>대 차 대 조 표</TABLE-GROUP>
         {_squished_table("자산  1.현금   2.매출채권미확정항목", "500,000,000300,000,000")}
       </SECTION-3>
     </SECTION-2>
     </DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    out = detect_squished_bs_total_assets(root, fin_type="B")
    assert "BS_S" not in out


def test_squished_bs_rejects_nonpositive_last_token():
    """총계는 항상 양수 — 마지막 토큰이 0 이하면 뭔가 잘못 걸린 것으로 보고 거부."""
    doc = f"""<DOCUMENT>
     <SECTION-2><TITLE>4. 재무제표</TITLE>
       <SECTION-3><TITLE>가. 대차대조표</TITLE>
         <TABLE-GROUP>대 차 대 조 표</TABLE-GROUP>
         {_squished_table("자산총계부채와자본총계", "500,000,000-500,000,000")}
       </SECTION-3>
     </SECTION-2>
     </DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    out = detect_squished_bs_total_assets(root, fin_type="B")
    assert "BS_S" not in out


def test_squished_bs_skipped_when_normal_table_present():
    """구간 안에 정상 다행 데이터표가 섞여 있으면(진짜 통짜-셀이 아님) 조용히 포기한다
    (방어적 이중 안전장치 — 호출측 필터와 별개로 이 함수 자신도 안전해야 함)."""
    doc = f"""<DOCUMENT>
     <SECTION-2><TITLE>4. 재무제표</TITLE>
       <SECTION-3><TITLE>가. 대차대조표</TITLE>{_PERIOD_MARK}
         {_data_table(('자산총계', '1,111,111,111'), ('부채총계', '222,222,222'))}
       </SECTION-3>
     </SECTION-2>
     </DOCUMENT>"""
    root = etree.fromstring(doc.encode())
    out = detect_squished_bs_total_assets(root, fin_type="B")
    assert "BS_S" not in out


def test_squished_bs_skips_consolidated_for_fin_type_b():
    """연결을 안 만드는 기업은 연결 섹션 자체를 안 본다(정상 경로와 동일 규약)."""
    root = etree.fromstring(SQUISHED_BS_DOC.encode())
    out = detect_squished_bs_total_assets(root, fin_type="B")
    assert "BS_C" not in out
