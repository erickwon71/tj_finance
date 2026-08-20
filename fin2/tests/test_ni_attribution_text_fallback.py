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

from fin2.audit.face_audit import _ni_attribution_text_candidates  # noqa: E402

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
    test_text_fallback_skipped_when_no_data_rows()
    print("OK")
