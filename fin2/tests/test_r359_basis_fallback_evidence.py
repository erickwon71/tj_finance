"""R359: from FY2015 a missing basis is filled from the other one only on printed evidence that
the period has no consolidated statements; separate is never filled from consolidated.

2026-11-20: DS단석 / 사조산업 / 도화엔지니어링 2026 Q3 were loaded from a viewer print whose
"4. 재무제표" was empty; the fallback copied consolidated into separate and Gate B failed it.
"""
from fin2.extract import consolidation_evidence as ce
from fin2.layer3 import combine

CHAIN = [("20160330000001", False), ("20160401000002", True)]


def _evidence(monkeypatch, value):
    seen = []
    monkeypatch.setattr(combine, "_period_filings_chrono", lambda s, c, y, p: CHAIN)

    def fake(session, src):
        seen.append(sorted(src.values()))
        return value
    monkeypatch.setattr(ce, "resolve_std_v3_no_consolidated_fs", fake)
    return seen


def test_consolidated_from_separate_needs_evidence(monkeypatch):
    seen = _evidence(monkeypatch, True)
    assert combine._basis_fallback_allowed(None, "00000001", 2016, "FY", "consolidated")
    # the amendment (no changed cell) is looked at too
    assert seen == [["20160330000001", "20160401000002"]]
    _evidence(monkeypatch, None)
    assert not combine._basis_fallback_allowed(None, "00000001", 2016, "FY", "consolidated")


def test_separate_needs_the_section2_pointer(monkeypatch):
    """No evidence of non-consolidation makes consolidated figures the separate ones; only a
    "4. 재무제표" section that points to section 2 does (R361, 원풍물산)."""
    _evidence(monkeypatch, True)
    monkeypatch.setattr(combine, "_period_has_evidence", lambda s, c, y, p, code: False)
    assert not combine._basis_fallback_allowed(None, "00000001", 2026, "Q3", "separate")
    seen = []
    monkeypatch.setattr(combine, "_period_has_evidence",
                        lambda s, c, y, p, code: seen.append(code) or True)
    assert combine._basis_fallback_allowed(None, "00144021", 2016, "FY", "separate")
    assert seen == ["separate_in_section2"]


def test_pre_2015_keeps_the_old_copy(monkeypatch):
    _evidence(monkeypatch, None)
    assert combine._basis_fallback_allowed(None, "00000001", 2014, "FY", "consolidated")
    assert combine._basis_fallback_allowed(None, "00000001", 2014, "FY", "separate")
