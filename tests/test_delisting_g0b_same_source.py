"""G0b compares list sizes only against a baseline from the same source (krx vs fdr)."""
from contextlib import contextmanager

from collector import delisting


class _FakeSession:
    def __init__(self, baselines):
        self.baselines = baselines      # {"KOSPI:krx": 801, "KOSPI:fdr": 942}

    def execute(self, _sql, params):
        key = params["m"].strip("%")
        return type("R", (), {"scalar": lambda self_: self.baselines.get(key)})()


def _patch(monkeypatch, baselines):
    @contextmanager
    def fake_session():
        yield _FakeSession(baselines)
    monkeypatch.setattr(delisting, "get_session", fake_session)


def test_source_switch_fdr_to_krx_is_not_a_shrink(monkeypatch):
    # 2026-10-03 baseline came from FDR (942, preferred shares included); KRX now gives 801.
    _patch(monkeypatch, {"KOSPI:fdr": 942})
    ok, why = delisting.check_source_trust({"KOSPI": {"used": "krx", "count": 801}}, krx_mode=True)
    assert ok, why


def test_real_shrink_in_same_source_still_skips(monkeypatch):
    _patch(monkeypatch, {"KOSPI:krx": 801})
    ok, why = delisting.check_source_trust({"KOSPI": {"used": "krx", "count": 700}}, krx_mode=True)
    assert not ok and "G0b" in why


def test_small_change_in_same_source_passes(monkeypatch):
    _patch(monkeypatch, {"KOSPI:krx": 801})
    ok, _ = delisting.check_source_trust({"KOSPI": {"used": "krx", "count": 795}}, krx_mode=True)
    assert ok
