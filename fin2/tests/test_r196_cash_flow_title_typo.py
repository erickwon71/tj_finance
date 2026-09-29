"""R196 — a cash-flow title misprinted as '연금흐름표' is still the cash-flow statement.

Hankuk Asset Trust 20161114000383 prints its consolidated cash-flow title as
'연 결 연 금 흐 름 표' (연금 instead of 현금). The classifier found no statement name, the
table was skipped and no consolidated CF was stored for the filing.
"""
from fin2.extract.statement_titles import classify_statement_in_body_section as classify


def test_typo_title_is_cash_flow():
    assert classify("연 결 연 금 흐 름 표 제 16 기 3분기", include_sce=True) == "CF"
    assert classify("연결연금흐름표", include_sce=False) == "CF"


def test_retirement_pension_word_is_not_a_cash_flow_title():
    assert classify("퇴직연금흐름표 제 16 기", include_sce=True) is None


def test_correct_title_and_other_statements_unchanged():
    assert classify("연 결 현 금 흐 름 표", include_sce=True) == "CF"
    assert classify("연 결 자 본 변 동 표", include_sce=True) == "SCE"
    assert classify("연 결 재 무 상 태 표", include_sce=True) == "BS"


def test_last_name_still_wins_with_typo():
    assert classify("※ 당분기 연결자본변동표는 …아니하였습니다. 연 결 연 금 흐 름 표", include_sce=True) == "CF"
