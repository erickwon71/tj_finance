"""R330 - more "no consolidated statements" wordings in the "2. 연결재무제표" section."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract import consolidation_evidence as ce  # noqa: E402


def _doc(body):
    return f'<SECTION-2><TITLE ATOC="Y">2. 연결재무제표</TITLE>{body}</SECTION-2><SECTION-2><TITLE>3. x</TITLE>'


@pytest.mark.parametrize("body", [
    "<P>해달사항 없음&cr;</P>",
    "<P>-해당사항 업음</P>",
    "<P>당사는 보고서 작성일 기준 현재 하당사항이 없습니다.</P>",
    "<P>- 연결재무제표 작성대상이 아닙니다.</P>",
    "<P>당사는 연결대상 종속회사가 존재하지 않으므로, 연결기준의 재무정보를 기재하지 않습니다.</P>",
    "<P>당사는 한국채택국제회계기준에 따른 연결재무제표를 작성하는 주권상장법인에 해당되지 않아 해당 내용을 생략합니다.</P>",
    "<P>※ 제24기까지는 연결기준이며, 제25기부터는 자회사에 대한 지배력 상실로 인해 개별기준입니다.</P>",
    "<P>※연결자회사 지분 매각에 따른 연결 제외됨.</P>",
    "<P>&#13;</P><P>&#13;</P><P>-</P>",
])
def test_r330_wordings_declare_absence(body):
    assert ce.detect_no_consolidated_fs(_doc(body))


def test_r330_never_fires_when_consolidated_statements_are_printed(monkeypatch):
    body = ("<P>2019년도 및 2018년도 재무제표는 개별재무제표(연결대상이 없음)로 표기 되었음을 알려드립니다</P>"
            "<TITLE>연결 재무상태표</TITLE><TABLE><TR><TD>자산총계</TD><TD>1,000</TD></TR></TABLE>")
    assert not ce.detect_no_consolidated_fs(_doc(body))
    monkeypatch.setattr(ce, "_R330_EXTRA_WORDINGS", False)
    assert not ce.detect_no_consolidated_fs(_doc("<P>해달사항 없음</P>"))
