"""Regression: the daily DQ gate re-audits only what layer 2 reloaded, full re-audit on Friday.

2026-11-17 daily: Gate B re-audited the whole 2015+ history of 1,276 companies (recheck=True)
and took 23.7 h of a 35 h run; about 3% had been reloaded. User decision 2026-11-19.
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import collect_new


def _args(**kw):
    return SimpleNamespace(no_verify=False, verify_fy_min=2015, verify_full=False, **kw)


def _run(monkeypatch, today, args):
    seen = {}

    def fake_gate(corps, fy_min, full=False):
        seen["full"] = full
        return {"corps": len(corps), "gb_fail_a": 0, "line_value_diff": 0, "dq3": 0,
                "new_gb_fail_a": 0, "new_line_value_diff": 0, "fail_corps": []}

    class _Date(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(collect_new, "run_dq_gate", fake_gate)
    monkeypatch.setattr(collect_new, "date", _Date)
    collect_new._verify_and_log({"ok_corps": ["00164788"]}, args)
    return seen["full"]


def test_weekday_is_incremental(monkeypatch):
    assert _run(monkeypatch, date(2026, 11, 19), _args()) is False      # Thursday


def test_friday_is_full(monkeypatch):
    assert _run(monkeypatch, date(2026, 11, 20), _args()) is True       # Friday


def test_flag_forces_full(monkeypatch):
    args = _args()
    args.verify_full = True
    assert _run(monkeypatch, date(2026, 11, 19), args) is True


def test_stale_sql_compares_reload_time_with_audit_time():
    # layer 2 reload (report_tables.parsed_at) after the audit (checked_at) invalidates the result
    assert "rt.parsed_at > fa.checked_at" in collect_new._GATEB_STALE_FACE_SQL
    assert "source_rcepts" in collect_new._GATEB_STALE_FACE_SQL
    assert "rt.parsed_at > fl.checked_at" in collect_new._GATEB_STALE_LINE_SQL
