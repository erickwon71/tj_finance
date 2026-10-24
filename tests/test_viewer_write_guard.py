"""viewer.xml must not be written when raw_report does not resolve to the primary volume."""
from pathlib import Path

from collector import viewer_source


def test_blocked_when_symlink_points_elsewhere(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    sd = tmp_path / "sd"
    primary.mkdir()
    sd.mkdir()
    link = tmp_path / "raw_report"
    link.symlink_to(sd)
    monkeypatch.setattr("collector.config.RAW_REPORT_DIR", link)
    monkeypatch.setattr("collector.storage_guard.PRIMARY_ROOT", primary)
    reason = viewer_source.viewer_write_blocked()
    assert reason and "PRIMARY" in reason


def test_allowed_when_symlink_points_to_primary(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    primary.mkdir()
    link = tmp_path / "raw_report"
    link.symlink_to(primary)
    monkeypatch.setattr("collector.config.RAW_REPORT_DIR", link)
    monkeypatch.setattr("collector.storage_guard.PRIMARY_ROOT", primary)
    assert viewer_source.viewer_write_blocked() is None


def test_blocked_when_symlink_dangling(tmp_path, monkeypatch):
    link = tmp_path / "raw_report"
    link.symlink_to(tmp_path / "missing")
    monkeypatch.setattr("collector.config.RAW_REPORT_DIR", link)
    assert viewer_source.viewer_write_blocked() is not None
