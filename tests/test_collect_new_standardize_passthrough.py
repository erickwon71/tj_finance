"""Regression: the daily ④ stage must hand every affected corp downstream.

2026-09-01 fact_v2 DROP made the old extract/reconcile worker fail for every corp
(2026-09-04 12/12 errors), so ok_corps stayed empty and layer2/std_v3/calendar were
silently skipped. The stage is now a pass-through (see collect_new._standardize_with_timeout).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import collect_new


def test_standardize_stage_passes_every_corp_through():
    corps = ["00126380", "00164779"]
    agg = collect_new._standardize_with_timeout(corps, timeout=1)
    assert agg["ok_corps"] == corps
    assert agg["errors"] == 0 and agg["timeout"] == 0


def test_run_batches_collects_ok_corps_without_touching_fact_v2(monkeypatch):
    seen = {}
    monkeypatch.setattr(collect_new, "_sync_cf_da", lambda ok: seen.setdefault("cf", list(ok)))
    monkeypatch.setattr(collect_new, "_sync_layer2_lines", lambda ok: seen.setdefault("l2", list(ok)))
    monkeypatch.setattr(collect_new, "_report_unit_self_contradiction", lambda ok: None)
    monkeypatch.setattr(collect_new, "_sync_shares_transcribe", lambda ok: None)
    agg = collect_new._run_standardize_batches(["A", "B", "C"], timeout=1, batch_size=2)
    assert agg["ok_corps"] == ["A", "B", "C"]
    assert seen["l2"] == ["A", "B"]  # first batch only (setdefault)
