"""R338 - stale adjusted-price boundaries and the per-stock re-base."""
from datetime import date

from analyzer.adjusted_history import plan_rows, rebase_after_market_row, step_is_stale


def test_stale_boundary_detected_korea_i():
    # 코나아이 052400: adjusted 33,300 -> 22,733 while the real close went 33,300 -> 34,000
    assert step_is_stale(pc=33300, c=22733, pr=33300, r=34000)


def test_real_ex_date_is_not_stale():
    # bonus issue ex-date: real close drops by 1.5, adjusted series continuous
    assert not step_is_stale(pc=20000, c=20600, pr=30000, r=20600)


def test_ordinary_day_is_not_stale():
    assert not step_is_stale(pc=33300, c=34000, pr=33300, r=34000)


def test_small_stale_boundary_kcc():
    # KCC 002380 2020-01-20/21: old basis 0.878 then 1.0, real close 233,500 -> 238,000
    assert step_is_stale(pc=205000, c=238000, pr=233500, r=238000)


def test_rounding_of_low_adjusted_price_is_not_stale():
    # adjusted 40 -> 41 on raw 400 -> 400: a 1-won rounding step on a low adjusted price
    assert not step_is_stale(pc=40, c=41, pr=400, r=401)


def test_after_market_row_rebased_with_new_factor():
    # stored on the old basis 1.0: KRX regular session o/h/l/c = 33,000/34,500/32,800/34,000
    old = {"open": 33000, "high": 34500, "low": 32800, "close": 34000, "close_raw": 34000}
    # source now on basis 1/1.5; its close is an after-market trade, its high includes it
    new = {"open": 22000, "high": 23500, "low": 21867, "close": 22800}
    out = rebase_after_market_row(old, new)
    assert out == {"open": 22000, "high": 23000, "low": 21867, "close": 22667}


def test_after_market_row_without_krx_close_is_kept():
    old = {"open": 1, "high": 1, "low": 1, "close": 100, "close_raw": None}
    assert rebase_after_market_row(old, {"open": 1, "high": 1, "low": 1, "close": 1}) is None


def test_plan_rows_existing_dates_only_and_changed_only():
    old = {
        date(2026, 10, 1): {"open": 30, "high": 31, "low": 29, "close": 30, "close_raw": 30},
        date(2026, 9, 1): {"open": 300, "high": 310, "low": 290, "close": 300, "close_raw": 300},
        date(2026, 8, 1): {"open": 200, "high": 210, "low": 190, "close": 200, "close_raw": 200},
    }
    fetched = [
        {"dt": date(2026, 7, 1), "open": 1, "high": 1, "low": 1, "close": 1},       # no such row
        {"dt": date(2026, 8, 1), "open": 200, "high": 210, "low": 190, "close": 200},  # unchanged
        {"dt": date(2026, 9, 1), "open": 30, "high": 31, "low": 29, "close": 30},    # re-based
    ]
    rows = plan_rows(old, fetched)
    assert rows == [{"dt": date(2026, 9, 1), "open": 30, "high": 31, "low": 29, "close": 30}]


def test_halt_days_are_excluded_from_detection_sql():
    from analyzer.adjusted_history import _STALE_SQL
    assert "COALESCE(volume, 1) > 0" in _STALE_SQL


def test_halt_row_takes_source_close_r351():
    # 047400 2026-10-27: halt row stored on the old basis (746), source prices it at 3,730
    old = {"open": None, "high": None, "low": None, "close": 746, "close_raw": 746}
    out = rebase_after_market_row(old, {"open": 0, "high": 0, "low": 0, "close": 3730})
    assert out == {"open": None, "high": None, "low": None, "close": 3730}


def test_halt_row_without_source_close_is_kept_r351():
    old = {"open": None, "high": None, "low": None, "close": 746, "close_raw": 746}
    assert rebase_after_market_row(old, {"close": None}) is None


def test_halt_detection_sql_looks_at_halt_days_r351():
    from analyzer.adjusted_history import _HALT_SQL
    assert "volume = 0" in _HALT_SQL
