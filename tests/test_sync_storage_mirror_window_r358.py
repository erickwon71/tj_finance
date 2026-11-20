"""R358: the incremental SD mirror lists files downloaded since the last successful mirror (not only
the last 48 hours), compares naive-UTC completed_at as an instant, and counts openrsync's
"Number of files transferred".

2026-11-16 run 60 died before ⑦ and the next mirror came 2.5 days later: 1,794 files received on
11-16 never reached the SD card, and every mirror logged files_sent=0.

The window test runs against the local DB inside a transaction that is rolled back.
"""
import contextlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sync_storage_mirror as m  # noqa: E402


def test_openrsync_stats_are_parsed():
    out = ("Number of files: 36\nNumber of files transferred: 2\n"
           "Total file size: 12712838 B\nTotal transferred file size: 2417232 B\n")
    assert m._parse_stats(out) == (2, 2417232)


def test_gnu_rsync_stats_still_parsed():
    out = "Number of regular files transferred: 5\nTotal transferred file size: 1,024 bytes\n"
    assert m._parse_stats(out) == (5, 1024)


@pytest.fixture
def tx(monkeypatch):
    from collector.db import SessionLocal, engine
    try:
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no local DB: {exc}")
    outer = conn.begin()
    session = SessionLocal(bind=conn)

    @contextlib.contextmanager
    def _gs():
        yield session

    monkeypatch.setattr(m, "get_session", _gs)
    monkeypatch.setattr("collector.raw_paths.on_disk_str", lambda p: p)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


def _one_task(s):
    row = s.execute(text("""SELECT rcept_no FROM download_tasks
        WHERE status = 'completed' AND file_path LIKE '%/raw_report/%' LIMIT 1""")).fetchone()
    if row is None:
        pytest.skip("no download task")
    s.execute(text("""UPDATE download_tasks SET file_path = '/x/raw_report/R358/probe.xml',
                      viewer_xml_path = NULL WHERE rcept_no = :r"""), {"r": row.rcept_no})
    return row.rcept_no


def test_files_since_last_success_are_listed_beyond_48h(tx):
    rc = _one_task(tx)
    # last success 4 days ago, file downloaded 3.5 days ago (naive UTC like datetime.utcnow)
    tx.execute(text("DELETE FROM storage_sync_log WHERE started_at > now() - interval '4 days'"))
    tx.execute(text("""INSERT INTO storage_sync_log (started_at, finished_at, status)
                       VALUES (now() - interval '4 days', now() - interval '4 days', 'success')"""))
    tx.execute(text("""UPDATE download_tasks
        SET completed_at = (now() - interval '84 hours') AT TIME ZONE 'UTC' WHERE rcept_no = :r"""),
               {"r": rc})
    assert "R358/probe.xml" in m._recent_relpaths(48)


def test_utc_completed_at_inside_the_window_is_listed(tx):
    rc = _one_task(tx)
    tx.execute(text("""INSERT INTO storage_sync_log (started_at, finished_at, status)
                       VALUES (now(), now(), 'success')"""))
    # 44 h ago as an instant; read as local time it would look 53 h old
    tx.execute(text("""UPDATE download_tasks
        SET completed_at = (now() - interval '44 hours') AT TIME ZONE 'UTC' WHERE rcept_no = :r"""),
               {"r": rc})
    assert "R358/probe.xml" in m._recent_relpaths(48)
