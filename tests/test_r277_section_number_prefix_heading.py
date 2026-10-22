"""R277: a legacy body heading with a section-number prefix is still a statement heading."""
import fin2.extract.statement_titles as st

HEADING = "1. 연결재무제표\n\n   연 결 재 무 상 태 표"


def test_r277_numbered_consolidated_heading_is_balance_sheet():
    res = st.classify_legacy_statement_heading(HEADING, include_sce=True)
    assert res is not None
    assert res == st.classify_legacy_statement_heading("연 결 재 무 상 태 표", include_sce=True)


def test_r277_switch_off_loses_heading():
    st._R277_SECTION_NUMBER_PREFIX = False
    try:
        assert st.classify_legacy_statement_heading(HEADING, include_sce=True) is None
    finally:
        st._R277_SECTION_NUMBER_PREFIX = True


def test_r277_plain_heading_unchanged():
    a = st.classify_legacy_statement_heading("연 결 재 무 상 태 표", include_sce=True)
    b = st.classify_legacy_statement_heading(HEADING, include_sce=True)
    assert a == b
