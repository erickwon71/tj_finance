"""R360 - more "no consolidated statements" wordings in the "2. 연결재무제표" section (2026-11-21).

Found when R359 stopped copying separate into consolidated without evidence: the sections said so
in other words. Measured: 11 of 66 candidate filings newly confirmed, 0 of 3,000 control filings
(std consolidated rows with real consolidated data)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract import consolidation_evidence as ce  # noqa: E402


def _doc(body):
    return f'<SECTION-2><TITLE ATOC="Y">2. 연결재무제표</TITLE>{body}</SECTION-2><SECTION-2><TITLE>3. x</TITLE>'


@pytest.mark.parametrize("body", [
    # 남해화학 20190401004960
    "<P>당사는 2016년중 농업회사법인 (주)바이오필드의 의결권 있는 지분 70%를 취득하여 연결범위에 포함하여 "
    "사업을 영위하다가 당기중 당사가 보유하고 있는 주식전량을 매각하여 연결재무를 작성하지 않습니다.</P>",
    # 올리패스 20240320000907 (the body names a comparative-year consolidated statement)
    "<P>제18기 재무제표는 당사의 종속회사가 2023년 중 연결대상에서 제외됨에 따라 개별 재무제표만을 작성하게 "
    "되었습니다. 또한, 비교 표시된 제17기, 제16기 재무제표는 연결재무제표 기준으로 작성하였습니다. 한편 제17기 "
    "연결포괄손익계산서 상 일부 금액은 당기 중 발생한 중단영업의 결과</P>",
    # 에이전트AI 20151117000242
    "<P>&#13;</P><P>본 보고서 작성 기준일 현재 계열회사는 없습니다.</P>",
    # 한국첨단소재 20240814003663 (user decision 2026-11-21)
    "<P>당사는 소규모기업에 해당되어 기업공시서식 작성기준에 따라 항목을 기재하지 않습니다.</P>",
])
def test_r360_wordings_declare_absence(body):
    assert ce.detect_no_consolidated_fs(_doc(body))


def test_r360_needs_the_section():
    assert not ce.detect_no_consolidated_fs(
        '<SECTION-2><TITLE>4. 재무제표</TITLE><P>당사는 연결재무를 작성하지 않습니다.</P></SECTION-2>')


def _doc2(sep_body, con_body="<TABLE><TR><TD>자산총계</TD></TR></TABLE>"):
    return (f'<SECTION-2><TITLE ATOC="Y">2. 연결재무제표</TITLE>{con_body}</SECTION-2>'
            f'<SECTION-2><TITLE ATOC="Y">4. 재무제표</TITLE>{sep_body}</SECTION-2>'
            f'<SECTION-2><TITLE>5. 재무제표 주석</TITLE>')


@pytest.mark.parametrize("sep_body", [
    "<P>- 2. 연결재무제표에 있으니, 참고하시기 바랍니다.&cr;</P>",          # 원풍물산 20160330002511
    "<P>- 2. 연결재무제표에 있으니, 참고하시기 바랍니다.&cr;</P><P>결손금처리계산서</P>"
    "<TABLE><TR><TD>미처리결손금</TD></TR></TABLE>",                       # 원풍물산 20170331001748
])
def test_r361_separate_section_pointing_to_section2(sep_body):
    """"4. 재무제표" says the statements are in section 2."""
    assert ce.compute_text_evidence(_doc2(sep_body))[0] == ce.EVIDENCE_SEPARATE_IN_SECTION2


@pytest.mark.parametrize("sep_body", [
    "",                                                     # empty viewer print (DS단석, R356)
    "<P>- 2. 연결재무제표에 있으니, 참고하시기 바랍니다.</P><P>재무상태표</P><TABLE><TR><TD>자산총계</TD></TR></TABLE>",
    "<P>당사의 재무제표는 아래와 같습니다. 주석은 2. 연결재무제표에 있으니 참고 바랍니다.</P>" + "가" * 150,
    "<P>재무상태표</P><TABLE><TR><TD>자산총계</TD></TR></TABLE>",
])
def test_r361_not_a_pointer(sep_body):
    assert ce.compute_text_evidence(_doc2(sep_body))[0] is None
