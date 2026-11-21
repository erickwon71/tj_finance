"""R371: one listed file the NAS does not hold must not stop the mirror of the others.

openrsync aborts the whole `--files-from` transfer (rc=23, nothing sent) when one entry fails its
stat; on 2026-10-22 and 10-23 that left six filings off the SD card.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sync_storage_mirror as m  # noqa: E402


def test_split_missing_by_existence():
    present, missing = m._split_missing(["a/1.xml", "a/2.xml", "b/3.xml"],
                                        exists=lambda p: not p.endswith("2.xml"))
    assert present == ["a/1.xml", "b/3.xml"] and missing == ["a/2.xml"]


def _setup(monkeypatch, tmp_path, rels):
    nas = tmp_path / "nas"
    sd = tmp_path / "sd"
    nas.mkdir(), sd.mkdir()
    for r in rels:
        (nas / r).parent.mkdir(parents=True, exist_ok=True)
        (nas / r).write_text("x")
    monkeypatch.setattr(m, "PRIMARY_ROOT", nas)
    monkeypatch.setattr(m, "BACKUP_ROOT", sd)
    monkeypatch.setattr(m, "TMP_LIST", str(tmp_path / "list.txt"))
    monkeypatch.setattr(m, "assert_storage", lambda **k: None)
    monkeypatch.setattr(m, "_free_gb", lambda p: 1000.0)
    monkeypatch.setattr(m, "_log_run", lambda *a, **k: None)
    return nas


def test_missing_entry_is_dropped_and_the_rest_is_sent(monkeypatch, tmp_path):
    nas = _setup(monkeypatch, tmp_path, ["K/a/1.xml", "K/a/3.xml"])
    monkeypatch.setattr(m, "_recent_relpaths", lambda h: ["K/a/1.xml", "K/a/2.viewer.xml", "K/a/3.xml"])
    sent = []

    def fake_run(cmd, **k):
        sent.append(Path(cmd[cmd.index("--files-from") + 1]).read_text().split())
        return SimpleNamespace(returncode=0, stdout="Number of files transferred: 2\n", stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    r = m.run_mirror()
    assert r["status"] == "success" and r["files_sent"] == 2
    assert sent == [["K/a/1.xml", "K/a/3.xml"]]
    assert r["missing"] == ["K/a/2.viewer.xml"]


def test_all_entries_missing_sends_nothing_and_succeeds(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(m, "_recent_relpaths", lambda h: ["K/a/2.viewer.xml"])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rsync")))
    r = m.run_mirror()
    assert r["status"] == "success" and r["files_sent"] == 0 and r["missing"] == ["K/a/2.viewer.xml"]


def test_file_vanishing_during_transfer_is_retried_without_it(monkeypatch, tmp_path):
    nas = _setup(monkeypatch, tmp_path, ["K/a/1.xml", "K/a/2.xml"])
    monkeypatch.setattr(m, "_recent_relpaths", lambda h: ["K/a/1.xml", "K/a/2.xml"])
    calls = []

    def fake_run(cmd, **k):
        lst = Path(cmd[cmd.index("--files-from") + 1])
        calls.append(lst.read_text().split())
        if len(calls) == 1:
            (nas / "K/a/2.xml").unlink()                      # vanishes after the pre-check
            return SimpleNamespace(returncode=23, stdout="", stderr="stat: No such file or directory")
        return SimpleNamespace(returncode=0, stdout="Number of files transferred: 1\n", stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    r = m.run_mirror()
    assert calls == [["K/a/1.xml", "K/a/2.xml"], ["K/a/1.xml"]]
    assert r["status"] == "success" and r["missing"] == ["K/a/2.xml"]


def test_rc23_without_a_missing_file_still_fails(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, ["K/a/1.xml"])
    monkeypatch.setattr(m, "_recent_relpaths", lambda h: ["K/a/1.xml"])
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=23, stdout="", stderr="other error"))
    import scripts.notify as n
    monkeypatch.setattr(n, "notify_failure", lambda *a, **k: None)
    assert m.run_mirror()["status"] == "failed"
