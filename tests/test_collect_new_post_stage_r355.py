"""R355: the daily post stages (⑤) also pick up corps with a downloaded filing that never went
through ⑤, and mark the filings done only after the stages ran.

2026-11-16 run 60 died after ④ batch 20/34; an out-of-band std_v3 rebuild filled the periods, so
run 61's ④ selector ("std_v3 lacks the period") skipped them and 529 corps never got Gate B, biz,
periodic biz, order backlog or doc sections (found via 아시아종묘 00867478 2026 Q3 periodic = 0).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import collect  # noqa: E402
from scripts import collect_new  # noqa: E402


def _wire(monkeypatch, pending, fail_mark=False):
    calls = []
    monkeypatch.setattr(collect, "db_now_utc", lambda: "T0")
    monkeypatch.setattr(collect, "post_stage_pending", lambda limit_corps=None: pending)

    def mark(corps, t):
        if fail_mark:
            raise RuntimeError("db down")
        calls.append(("mark", tuple(corps), t))
        return 7

    monkeypatch.setattr(collect, "mark_post_stage_done", mark)
    monkeypatch.setattr(collect_new, "_verify_and_log",
                        lambda agg, args: calls.append(("verify", tuple(agg["ok_corps"]))))
    monkeypatch.setattr(collect_new, "_sync_biz_metrics",
                        lambda corps, pend=None: calls.append(("biz", tuple(corps), pend)))
    monkeypatch.setattr(collect_new, "_sync_order_backlog",
                        lambda corps: calls.append(("backlog", tuple(corps))))
    monkeypatch.setattr(collect_new, "_sync_doc_sections",
                        lambda corps: calls.append(("doc", tuple(corps))))
    return calls


def _args():
    return SimpleNamespace(no_verify=False, verify_fy_min=2015, verify_full=False)


def test_pending_corps_join_every_post_stage(monkeypatch):
    pending = {"00867478": {(2026, "quarter")}, "00100001": {(2026, "half")}}
    calls = _wire(monkeypatch, pending)
    agg = {"ok_corps": ["00100001"]}
    collect_new._run_post_stages(agg, _args(), ["00100001", "00200002"])
    assert calls[0] == ("verify", ("00100001", "00867478"))
    assert calls[1] == ("biz", ("00100001", "00200002", "00867478"), pending)
    assert calls[2] == ("backlog", ("00100001", "00200002", "00867478"))
    assert calls[3] == ("doc", ("00100001", "00200002", "00867478"))
    # marked last, with the selection time taken before the stages ran
    assert calls[4] == ("mark", ("00100001", "00200002", "00867478"), "T0")


def test_mark_failure_is_not_fatal(monkeypatch):
    calls = _wire(monkeypatch, {}, fail_mark=True)
    collect_new._run_post_stages({"ok_corps": []}, _args(), ["00100001"])
    assert [c[0] for c in calls] == ["verify", "biz", "backlog", "doc"]


def test_pending_lookup_failure_falls_back_to_today(monkeypatch):
    calls = _wire(monkeypatch, {})

    def boom(limit_corps=None):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(collect, "post_stage_pending", boom)
    collect_new._run_post_stages({"ok_corps": ["00100001"]}, _args(), ["00100001"])
    assert calls[1][1] == ("00100001",)


def test_older_pending_year_gets_year_scoped_sync(monkeypatch):
    import collector.biz_metrics as bm
    import collector.biz_metrics_periodic as bp
    import collector.db as cdb
    seen = []

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            pass

    monkeypatch.setattr(cdb, "get_session", lambda: _S())
    monkeypatch.setattr(bm, "sync_biz_metrics_corp", lambda s, c, y: seen.append(("annual", c, y)))
    monkeypatch.setattr(bp, "sync_biz_periodic",
                        lambda corps, year=None: seen.append(("periodic", corps[0], year)) or {})
    collect_new._sync_biz_pending_years({"01158632": {(2017, "quarter"), (2017, "half"),
                                                      (2019, "quarter"), (2016, "annual")}})
    assert seen == [("annual", "01158632", 2016), ("periodic", "01158632", 2017),
                    ("periodic", "01158632", 2019)]
