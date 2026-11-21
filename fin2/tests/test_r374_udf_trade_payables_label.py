"""R374 — the Gate B face reader admits the company-extension row labelled "매입채무 및 계약부채" as
trade_payables (docs/rules/30_audit_verify.md R374). Real-file test; skipped when the raw XML is absent."""
from __future__ import annotations

from pathlib import Path

import pytest

from fin2.audit.face_audit import read_report_face_xbrl

_ROOTS = (Path("/Volumes/dart_data/raw_report"), Path(__file__).resolve().parents[2] / "raw_report")


def _raw():
    for root in _ROOTS:
        try:
            hits = list(root.glob("KOSDAQ/01189438_*/quarter/2026/20260515000592.xml"))
        except OSError:
            continue
        if hits:
            return hits[0]
    return None


def test_extension_acode_payables_and_contract_liabilities_row_is_read():
    raw = _raw()
    if raw is None:
        pytest.skip("raw XML not mounted")
    lines = read_report_face_xbrl(raw)
    sep = [l for l in lines if l.canonical == "bs.trade_payables" and l.basis == "separate"]
    labels = {l.row_label: l.displayed_value for l in sep}
    assert labels.get("매입채무 및 계약부채") == 4_316_750_374
