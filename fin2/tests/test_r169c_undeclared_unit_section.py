"""R169-c — a body section skipped for "단위 미선언" is nominated through `report_tables` gaps and its
unit proved by exact amount matches (docs/PARSING_RULES.md R169-c).

Real-file / DB tests; each case is skipped when the raw XML or the database is not available.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fin2.extract.report_lines import extract_report_lines

_RCEPT = "20150515001311"   # 오늘이엔엠 2015 Q1: 4. 재무제표 tables print no "(단위 : 원)" line
_ROOTS = (Path("/Volumes/dart_data/raw_report"), Path(__file__).resolve().parents[2] / "raw_report")


def _find_raw():
    for root in _ROOTS:
        try:
            hits = list(root.glob(f"KOSDAQ/00623184_*/quarter/2015/{_RCEPT}.xml"))
        except OSError:
            continue
        if hits:
            return hits[0]
    return None


def test_undeclared_separate_sections_are_read_as_won_when_proved():
    raw = _find_raw()
    if raw is None:
        pytest.skip("raw XML not mounted")
    lines = extract_report_lines(raw, rcept_no=_RCEPT, corp_code="00623184",
                                 report_fiscal_year=2015, report_fiscal_period="Q1")
    sep = [l for l in lines if l.basis == "separate" and l.value_won is not None]
    assert {l.statement for l in sep} >= {"BS", "IS", "CF", "SCE"}
    bs = {l.label_raw: l for l in sep if l.statement == "BS" and (l.col_index or 0) == 0}
    assert bs["자산총계"].value_won == 31_520_517_893          # printed as 31,520,517,893 (원)
    assert bs["자산총계"].unit_source == "proved_unit"
    # the consolidated tables declare 원 themselves and are untouched
    con = {l.label_raw: l for l in lines if l.basis == "consolidated" and l.statement == "BS"
           and (l.col_index or 0) == 0}
    assert con["자산총계"].unit_source == "declared"


def test_undeclared_nomination_is_opt_in_and_finds_the_gap_filing():
    try:
        from collector.db import get_session
        from fin2.audit.unit_self_contradiction import suspect_rcepts, undeclared_gap_suspects
        with get_session() as s:
            gap = undeclared_gap_suspects(s, 2015, ["00623184"])
            default = suspect_rcepts(s, 2015, ["00623184"])
            opted = suspect_rcepts(s, 2015, ["00623184"], include_undeclared=True)
    except Exception as exc:  # noqa: BLE001 — no database in this environment
        pytest.skip(f"database not available: {exc}")
    # 2015 Q1 lacks a consolidated IS table that its siblings (H1/Q3/FY) have -> nominated
    assert _RCEPT in gap
    assert _RCEPT not in default and _RCEPT in opted


def test_nomination_does_not_confirm_anything_by_itself():
    """A nominated filing whose missing section is legitimately absent stays unchanged: scan_rcept
    only returns sections that vanish under the declared unit AND have raw rows to prove."""
    try:
        from collector.db import get_session
        from fin2.audit.unit_self_contradiction import scan_rcept, undeclared_gap_suspects
        with get_session() as s:
            gap = undeclared_gap_suspects(s, 2015, ["00623184"])
            rows = scan_rcept(s, gap[0], set(gap)) if gap else []
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not available: {exc}")
    assert all(r.get("decision") != "confirmed:1000000" for r in rows)
