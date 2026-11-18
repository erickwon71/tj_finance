"""R337 - the daily capital-event scan resumes from the last successful store."""
from datetime import date

from collector.dart_capital import CAPITAL_RESUME_MAX_DAYS, capital_sync_start

TODAY = date(2026, 11, 18)


def test_no_history_uses_plain_lookback():
    assert capital_sync_start(TODAY, None, 5) == date(2026, 11, 13)


def test_recent_store_keeps_plain_lookback():
    # stored yesterday: resume point (11-12) is earlier than plain lookback (11-13) by one day
    assert capital_sync_start(TODAY, date(2026, 11, 17), 5) == date(2026, 11, 12)


def test_outage_resumes_from_last_store():
    # daily job down since 09-19 (the 코나아이 20260914000031 gap): scan from 09-14
    assert capital_sync_start(TODAY, date(2026, 9, 19), 5) == date(2026, 9, 14)


def test_long_outage_is_capped():
    start = capital_sync_start(TODAY, date(2025, 1, 1), 5)
    assert (TODAY - start).days == CAPITAL_RESUME_MAX_DAYS


def test_future_or_today_store_never_narrows_window():
    assert capital_sync_start(TODAY, TODAY, 5) == date(2026, 11, 13)
