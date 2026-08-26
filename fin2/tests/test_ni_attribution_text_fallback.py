"""R35(2026-08-20) 회귀 테스트 — `_ni_attribution_text_candidates()`.

배경: P3-1 '원인 A' 후속(부록C). 일부 필링은 NI 귀속('...의 귀속') 표 전체가 XBRL
미태깅(순수 `<TD>`)이라 `_ni_attribution_structural_candidates()`(TE 전용)가 통째로
못 본다 — 실측 56개사/527건, std_v3 값 자체는 원문과 일치(감사기 커버리지 공백).

실행: python fin2/tests/test_ni_attribution_text_fallback.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.audit.face_audit import (  # noqa: E402
    _ni_attribution_text_candidates, _with_ni_attribution_text_fallback, FaceLine,
)

# 케이씨씨/엘에스일렉트릭 원문 구조를 축약 재현: SECTION-2(연결재무제표) 안에
# 표제표 + 데이터표(순수 TD, TE 없음), NI 귀속 섹션은 앵커 뒤 지배/비지배 두 행.
_XML_UNTAGGED = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 제68기 2023년 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>매출액</TD><TD>1,000,000,000</TD></TR>
    <TR><TD>당기순이익(손실)의 귀속</TD><TD>&#12288;</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD>700,000,000</TD></TR>
    <TR><TD>&#12288;비지배주주지분</TD><TD>50,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""


def test_text_fallback_finds_controlling_and_noncontrolling():
    root = etree.fromstring(_XML_UNTAGGED.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = [l for l in lines if l.canonical == "is.controlling_ni"]
    ncl = [l for l in lines if l.canonical == "is.noncontrolling_ni"]
    assert any(l.amount_won == 700_000_000 for l in ctrl), ctrl
    assert any(l.amount_won == 50_000_000 for l in ncl), ncl
    # 안전장치: 태그 없는 후보는 전부 from_gapfill=True(단조성 계약, FAIL 승격 금지).
    assert all(l.from_gapfill for l in lines)
    assert all(l.basis == "consolidated" for l in lines)


def test_call_site_fallback_condition_holds_for_untagged_doc():
    # `read_report_face_xbrl()`은 TE 경로가 is.controlling_ni/noncontrolling_ni 를 **하나도**
    # 못 찾을 때만 이 폴백을 부른다(성능, 함수 docstring §호출측 참고) — 그 전제조건을 검증한다.
    from fin2.audit.face_audit import _ni_attribution_structural_candidates
    root = etree.fromstring(_XML_UNTAGGED.encode("utf-8"))
    te_only = _ni_attribution_structural_candidates(root)
    assert not any(l.canonical in ("is.controlling_ni", "is.noncontrolling_ni") for l in te_only), (
        "이 문서는 TE 가 전혀 없으므로 TE 경로는 아무 것도 못 찾아야 한다")


def test_text_fallback_takes_only_current_period_column_fy():
    # R36(2026-08-20) — FY(연간비교) 표는 [당기,전기,전전기] 순. 이전 컬럼(전기/전전기)이
    # 지배/비지배 값 후보로 잘못 섞여 나오면 안 된다(성도이엔지 실측: 모든 FY 필링에서
    # 재현됐던 값불일치 오탐의 근본원인). 첫 컬럼(당기)만 채택.
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 제68기 2023년 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>매출액</TD><TD>1,000,000,000</TD><TD>900,000,000</TD><TD>800,000,000</TD></TR>
    <TR><TD>당기순이익(손실)의 귀속</TD><TD>&#12288;</TD><TD>&#12288;</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD>700,000,000</TD><TD>650,000,000</TD><TD>600,000,000</TD></TR>
    <TR><TD>&#12288;비지배주주지분</TD><TD>50,000,000</TD><TD>45,000,000</TD><TD>40,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {700_000_000}, f"당기(첫 컬럼)만 남아야 함, 전기/전전기 섞임: {ctrl}"
    assert ncl == {50_000_000}, ncl


def test_text_fallback_takes_cumulative_column_interim():
    # R36(2026-08-20) — H1/Q3(interim) 표는 [당기3개월,당기누적,전기3개월,전기누적] 4열.
    # 첫 컬럼(당기3개월)은 누적이 아니므로 std_v3(항상 누적) 와 다르다 — '누적' 헤더 토큰이
    # 붙은 컬럼을 골라야 한다(성도이엔지 2023H1 실측: 당기3개월=1,451,210,911 이 아니라
    # 당기누적=1,296,834,534 이 std_v3 값이었음).
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD></TD><TD>3개월</TD><TD>누적</TD><TD>3개월</TD><TD>누적</TD></TR>
    <TR><TD>매출액</TD><TD>1,000,000,000</TD><TD>1,900,000,000</TD><TD>950,000,000</TD><TD>1,800,000,000</TD></TR>
    <TR><TD>반기순이익(손실)의 귀속</TD><TD>&#12288;</TD><TD>&#12288;</TD><TD>&#12288;</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD>1,451,210,911</TD><TD>1,296,834,534</TD><TD>2,501,296,907</TD><TD>8,399,952,262</TD></TR>
    <TR><TD>&#12288;비지배주주지분</TD><TD>-9,988,666</TD><TD>96,377,136</TD><TD>-290,926,975</TD><TD>79,883,313</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {1_296_834_534}, f"당기누적 컬럼만 남아야 함(당기3개월 아님): {ctrl}"
    assert ncl == {96_377_136}, ncl


def test_text_fallback_note_column_offset_corrected():
    """★2026-08-24 — 라벨과 값 사이에 '주석' 컬럼이 구조적으로 있는 표(다른 행의 콤마
    다중참조로 table_has_note_column=True) 에서, 지배/비지배 행의 주석칸이 **비어
    있어도**(이 행은 주석 없음) 당기누적 컬럼을 정확히 골라야 한다 — 코리안리
    20211115001569 원문대조로 확정된 오정렬(`gateb_bugA_col_misselect_optionA_
    rootfix_plan_2026-08-24.md` §3-4)의 합성 재현. 매출액 행의 '1,2'(콤마 다중참조)가
    이 표에 주석 컬럼이 있음을 확정한다."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD></TD><TD>3개월</TD><TD>누적</TD><TD>3개월</TD><TD>누적</TD></TR>
    <TR><TD>매출액</TD><TD>1,2</TD><TD>1,000,000,000</TD><TD>1,900,000,000</TD><TD>950,000,000</TD><TD>1,800,000,000</TD></TR>
    <TR><TD>반기순이익(손실)의 귀속</TD><TD></TD><TD>&#12288;</TD><TD>&#12288;</TD><TD>&#12288;</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD></TD><TD>1,451,210,911</TD><TD>1,296,834,534</TD><TD>2,501,296,907</TD><TD>8,399,952,262</TD></TR>
    <TR><TD>&#12288;비지배주주지분</TD><TD></TD><TD>-9,988,666</TD><TD>96,377,136</TD><TD>-290,926,975</TD><TD>79,883,313</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {1_296_834_534}, (
        f"주석칸 offset 보정 없이 idx 그대로 읽으면 당기3개월(1,451,210,911)을 오채택: {ctrl}")
    assert ncl == {96_377_136}, ncl


def test_skipgate_still_adds_correct_candidate_when_wrong_one_already_present():
    """★2026-08-26(R45 후속, `docs/plans/faceaudit_ni_attribution_skipgate_design_
    2026-08-26.md` §2-A) — 이전 구현은 `is.controlling_ni`/`is.noncontrolling_ni`가
    이미 `lines`에 있으면(옳든 그르든) 이 폴백을 아예 안 불렀다. 일반 라벨매퍼가 총포괄손익
    귀속 섹션을 순이익 귀속으로 오매핑해 두 canonical을 먼저 채워버리는 문서(00913689
    세경하이테크 등, 247건 원문실행대조 중 171건/26개사 확인)에서, 진짜 정답을 아는
    이 구조인식 폴백이 스킵돼 정답이 후보 풀에 영원히 안 들어갔다.

    이 테스트는 그 상황을 합성 재현한다: `lines`에 이미(총포괄손익 귀속 섹션에서 나온,
    실제로는 틀린) is.controlling_ni 값이 있는 상태에서 폴백을 호출해도, 문서 안의
    진짜 '당기순이익(손실)의 귀속' 섹션 값이 후보로 추가돼야 한다."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 제68기 2023년 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>매출액</TD><TD>1,000,000,000</TD></TR>
    <TR><TD>당기순이익(손실)의 귀속</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD>700,000,000</TD></TR>
    <TR><TD>&#12288;비지배주주지분</TD><TD>50,000,000</TD></TR>
    <TR><TD>총포괄손익의 귀속</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분순이익(손실)</TD><TD>999,000,000</TD></TR>
    <TR><TD>&#12288;비지배주주지분순이익(손실)</TD><TD>10,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    # 일반 라벨매퍼가 총포괄손익 귀속 행을 이미 (틀리게) 채워둔 상태를 합성.
    wrong_already_present = [
        FaceLine(statement="IS", basis="consolidated", acode="지배주주지분순이익(손실)",
                 canonical="is.controlling_ni", label="지배주주지분순이익(손실)",
                 displayed_value=999_000_000, adecimal=0, is_cumulative=True),
        FaceLine(statement="IS", basis="consolidated", acode="비지배주주지분순이익(손실)",
                 canonical="is.noncontrolling_ni", label="비지배주주지분순이익(손실)",
                 displayed_value=10_000_000, adecimal=0, is_cumulative=True),
    ]
    result = _with_ni_attribution_text_fallback(wrong_already_present, root)
    ctrl_vals = {l.amount_won for l in result if l.canonical == "is.controlling_ni"}
    ncl_vals = {l.amount_won for l in result if l.canonical == "is.noncontrolling_ni"}
    assert 700_000_000 in ctrl_vals, f"진짜 순이익귀속 정답이 빠짐: {ctrl_vals}"
    assert 50_000_000 in ncl_vals, f"진짜 순이익귀속 정답이 빠짐: {ncl_vals}"
    # 기존(틀린) 후보도 그대로 남아있어야 함(넓히기만, 선택 아님 — 단조성 계약).
    assert 999_000_000 in ctrl_vals
    assert 10_000_000 in ncl_vals


def test_text_fallback_reads_acode_less_te_row():
    """★R47(2026-08-26, `docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md`
    §2-B) — 일부 필러는 NI귀속 행을 `<TD>`가 아니라 `<TE>`로 렌더링하면서도 ACODE 를 전혀
    안 붙인다(원문 실측: 00163691 유수홀딩스 2023FY 등 22건). TE 자매함수는 ACODE 없는 셀을
    후보로 안 내므로, 스킵게이트가 "TE면 무조건 skip"이던 예전 구현에서는 이 행이 양쪽
    함수 모두에서 침묵했다 — ACODE 없는 TE는 TD처럼 직접 읽어야 한다."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TE>매출액</TE><TE>1,000,000,000</TE></TR>
    <TR><TE>당기순이익의 귀속</TE><TE></TE></TR>
    <TR><TE>지배기업소유주지분</TE><TE>700,000,000</TE></TR>
    <TR><TE>비지배지분</TE><TE>50,000,000</TE></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {700_000_000}, f"ACODE 없는 TE 행을 못 읽음: {ctrl}"
    assert ncl == {50_000_000}, ncl


def test_text_fallback_anchor_survives_numbering_prefix():
    """★R47-b(2026-08-26, `docs/PARSING_RULES.md`) — 앵커 라벨 앞에 로마숫자 번호("XⅢ." —
    ASCII 'X'+유니코드 'Ⅲ' 혼용 표기, 하이록코리아 실측)가 붙으면 `_NI_TOTAL_RE`의 `^`-앵커가
    깨져 섹션이 아예 안 열렸다(70건 중 24건). 접두사를 벗겨낸 뒤 앵커 매칭해야 한다."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>XⅢ.당기순이익(손실)의 귀속</TD><TD>&#12288;</TD></TR>
    <TR><TD>(1)지배기업소유주지분</TD><TD>700,000,000</TD></TR>
    <TR><TD>(2)비지배지분</TD><TD>50,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {700_000_000}, f"번호 접두사 때문에 앵커가 안 열림: {ctrl}"
    assert ncl == {50_000_000}, ncl


def test_text_fallback_anchor_survives_entity_prefix_and_sonsil():
    """★R47-b — "연결"류 개체 접두사 + 조사 "의" + "순손실"(원래 정규식은 "순이익"/"순손익"만
    허용) 조합이 앵커를 놓쳤다(서희건설 00219848 실측: "연결당기의순손실")."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>연결당기의순손실</TD><TD>&#12288;</TD></TR>
    <TR><TD>지배기업소유주에 귀속될 당기순손실</TD><TD>-700,000,000</TD></TR>
    <TR><TD>비지배기업소유주에 귀속될 당기순이익(손실)</TD><TD>-50,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    ctrl = {l.amount_won for l in lines if l.canonical == "is.controlling_ni"}
    ncl = {l.amount_won for l in lines if l.canonical == "is.noncontrolling_ni"}
    assert ctrl == {-700_000_000}, f"연결 접두사/순손실 조합 때문에 앵커가 안 열림: {ctrl}"
    assert ncl == {-50_000_000}, ncl


def test_text_fallback_anchor_prefix_strip_does_not_admit_ebt_row():
    """회귀 가드 — 접두사 제거가 "법인세비용차감전순이익"(EBT, 순이익귀속 앞의 상위 소계)을
    앵커로 잘못 열지 않아야 한다. 원본 `_NI_TOTAL_RE`의 안전장치(코아시아씨엠 회귀, R24)가
    접두사 스트리핑 뒤에도 유지되는지 확인."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>Ⅹ.법인세비용차감전순이익(손실)</TD><TD>&#12288;</TD></TR>
    <TR><TD>지배기업소유주지분</TD><TD>999,000,000</TD></TR>
    <TR><TD>비지배지분</TD><TD>1,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    assert lines == [], f"EBT 소계 행이 앵커로 잘못 열림: {lines}"


def test_text_fallback_still_skips_acode_bearing_te_row():
    """R47 도입 후에도 ACODE 가 진짜 있는 TE 행은 여전히 skip 되어야 한다(TE 자매함수가
    처리할 몫 — 중복 방지 계약 유지, 회귀 가드)."""
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TE>매출액</TE><TE>1,000,000,000</TE></TR>
    <TR><TE>당기순이익의 귀속</TE><TE></TE></TR>
    <TR><TE>지배기업소유주지분</TE><TE ACODE="ifrs-full_ProfitLossAttributableToOwnersOfParent" ACONTEXT="CFY0Y">700,000,000</TE></TR>
    <TR><TE>비지배지분</TE><TE ACODE="ifrs-full_ProfitLossAttributableToNoncontrollingInterests" ACONTEXT="CFY0Y">50,000,000</TE></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    assert lines == [], f"ACODE 있는 TE 행은 TE 자매함수 몫 — text 폴백은 침묵해야 함: {lines}"


def test_text_fallback_skipped_when_no_data_rows():
    # 앵커만 있고 지배/비지배 두 행이 갖춰지지 않으면(형태 불명확) 아무 것도 안 낸다 — 추측 금지.
    xml = """<DOCUMENT>
 <SECTION-2>
  <TITLE>2. 연결재무제표</TITLE>
  <TABLE-GROUP>
   <TABLE><TR><TD>연결 손익계산서 제68기 2023년 (단위 : 원)</TD></TR></TABLE>
   <TABLE>
    <TR><TD>매출액</TD><TD>1,000,000,000</TD></TR>
    <TR><TD>당기순이익(손실)의 귀속</TD><TD>&#12288;</TD></TR>
    <TR><TD>&#12288;지배주주지분</TD><TD>700,000,000</TD></TR>
   </TABLE>
  </TABLE-GROUP>
 </SECTION-2>
</DOCUMENT>"""
    root = etree.fromstring(xml.encode("utf-8"))
    lines = _ni_attribution_text_candidates(root)
    assert lines == [], f"비지배 짝이 없는 미완성 섹션은 스킵돼야 함: {lines}"


if __name__ == "__main__":
    test_text_fallback_finds_controlling_and_noncontrolling()
    test_call_site_fallback_condition_holds_for_untagged_doc()
    test_text_fallback_takes_only_current_period_column_fy()
    test_text_fallback_takes_cumulative_column_interim()
    test_text_fallback_note_column_offset_corrected()
    test_skipgate_still_adds_correct_candidate_when_wrong_one_already_present()
    test_text_fallback_reads_acode_less_te_row()
    test_text_fallback_anchor_survives_numbering_prefix()
    test_text_fallback_anchor_survives_entity_prefix_and_sonsil()
    test_text_fallback_anchor_prefix_strip_does_not_admit_ebt_row()
    test_text_fallback_still_skips_acode_bearing_te_row()
    test_text_fallback_skipped_when_no_data_rows()
    print("OK")
