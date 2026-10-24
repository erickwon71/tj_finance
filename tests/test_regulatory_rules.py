"""classify_regulatory_event needs _REGULATORY_RULES (deleted by accident in fbd053f, 2026-10-05;
the daily regulatory sync failed with NameError until restored)."""
from collector.dart_extra import classify_regulatory_event


def test_rules_defined_and_classify():
    assert classify_regulatory_event("관리종목지정") == ("admin_issue", False)
    assert classify_regulatory_event("관리종목지정해제") == ("admin_issue", True)
    assert classify_regulatory_event("매매거래정지해제") == ("trading_halt", True)
    assert classify_regulatory_event("상장폐지결정") == ("delisting", False)
    assert classify_regulatory_event("분기보고서") is None
