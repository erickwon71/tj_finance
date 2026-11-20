"""R356: a filing loaded from the web-viewer print whose main XML arrived later
(download_tasks.layer2_reload_pending) re-enters ④ even though its period is already in std_v3,
its layer 2 is not empty and its corp filed nothing today (the main path's `only`).

2026-11-16/17: DS단석 00108612 / 사조산업 00124799 / 도화엔지니어링 00114552 2026 Q3 were loaded
from a viewer print whose "4. 재무제표" section was empty; the main XML came the same evening, but
the flag was never consumed (335 filings) and Gate B failed the separate statements (fail_a).

Runs against the local DB inside a transaction that is rolled back.
"""
import contextlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import collect  # noqa: E402

# A completed main-XML regular filing whose period is in std_v3 and whose layer 2 is loaded,
# for a corp with no flagged filing: the selector must not pick it unless flagged.
_PICK_SQL = """
    SELECT f.rcept_no, f.corp_code
    FROM filings f JOIN download_tasks dt USING (rcept_no)
    WHERE dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
      AND f.report_type = 'annual' AND f.fiscal_year = 2024
      AND NOT COALESCE(dt.layer2_reload_pending, FALSE)
      AND EXISTS (SELECT 1 FROM std_financials_v3 s WHERE s.corp_code = f.corp_code
                  AND s.fiscal_year = f.fiscal_year AND s.fiscal_period = f.fiscal_period)
      AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
    LIMIT 200
"""


@pytest.fixture
def tx_session(monkeypatch):
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

    monkeypatch.setattr(collect, "get_session", _gs)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


def _unselected_corp(session):
    for rcept, corp in session.execute(text(_PICK_SQL)).fetchall():
        if corp not in collect.needs_standardize_corps(only=[corp]):
            return rcept, corp
    pytest.skip("no settled filing to test with")


def test_flagged_filing_is_selected_outside_only(tx_session):
    rcept, corp = _unselected_corp(tx_session)
    assert corp not in collect.needs_standardize_corps(only=["00000000"])
    tx_session.execute(text("UPDATE download_tasks SET layer2_reload_pending = TRUE "
                            "WHERE rcept_no = :r"), {"r": rcept})
    # main daily path: `only` = today's filers, which does not include this corp
    assert corp in collect.needs_standardize_corps(only=["00000000"])
    # --standardize-only resume path: no `only`
    assert corp in collect.needs_standardize_corps()


def test_only_still_limits_unflagged_corps(tx_session):
    rcept, corp = _unselected_corp(tx_session)
    tx_session.execute(text("DELETE FROM report_lines WHERE rcept_no = :r"), {"r": rcept})
    tx_session.execute(text("DELETE FROM note_lines WHERE rcept_no = :r"), {"r": rcept})
    tx_session.execute(text("UPDATE download_tasks SET created_at = now() WHERE rcept_no = :r"),
                       {"r": rcept})
    # recent filing with empty layer 2: picked when in `only`, not when outside it
    assert corp in collect.needs_standardize_corps(only=[corp])
    assert corp not in collect.needs_standardize_corps(only=["00000000"])
