"""Regression: the daily DQ gate re-audits only results whose input changed (R346, R346-b).

2026-11-17 daily: Gate B re-audited the whole 2015+ history of 1,276 companies (recheck=True)
and took 23.7 h of a 35 h run; about 3% had been reloaded. User decisions 2026-11-19: incremental
re-audit, then a std-row fingerprint instead of a weekly full re-audit.
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


def test_friday_is_incremental_too(monkeypatch):
    # R346-b: the fingerprint replaced the weekly full re-audit
    assert _run(monkeypatch, date(2026, 11, 20), _args()) is False      # Friday


def test_flag_forces_full(monkeypatch):
    args = _args()
    args.verify_full = True
    assert _run(monkeypatch, date(2026, 11, 19), args) is True


def test_stale_face_sql_uses_the_stamped_fingerprint():
    from scripts import gateb_audit
    sql = collect_new._gateb_stale_face_sql(gateb_audit.INPUT_FP_EXPR)
    assert "fa.input_fp IS DISTINCT FROM md5((to_jsonb(s) - 'built_at')::text)" in sql
    assert "fa.reader_version IS DISTINCT FROM :rv" in sql
    # the stamp after the audit uses the same expression
    assert gateb_audit.INPUT_FP_EXPR in gateb_audit._STAMP_INPUT_FP_SQL


def test_stale_line_sql_reload_or_reader_version():
    sql = collect_new._GATEB_STALE_LINE_SQL
    assert "rt.parsed_at > fl.checked_at" in sql
    assert "fl.reader_version IS DISTINCT FROM :rv" in sql
