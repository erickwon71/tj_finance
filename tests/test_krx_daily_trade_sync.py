"""scripts/krx_daily_trade_sync.py - KRX daily trade rows -> stock_prices close_raw / list_shares."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.krx_client import KrxUnavailable  # noqa: E402
from scripts import krx_daily_trade_sync as kd  # noqa: E402


class _Res:
    def __init__(self, rowcount=0, scalar=0):
        self.rowcount, self._s = rowcount, scalar

    def scalar(self):
        return self._s


class _Session:
    def __init__(self):
        self.inserted = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.startswith("INSERT INTO _krx_day"):
            self.inserted = params
        if sql.strip().startswith("UPDATE stock_prices"):
            self.update_sql, self.update_params = sql, params
            return _Res(rowcount=len(self.inserted or []))
        return _Res()


def test_rows_are_parsed_and_bad_rows_skipped(monkeypatch):
    monkeypatch.setattr(kd, "fetch_daily_trade", lambda m, d: [
        {"ISU_CD": "340570", "TDD_CLSPRC": "30,650", "LIST_SHRS": "16070120", "MKTCAP": "492549178000"},
        {"ISU_CD": "0001A0", "TDD_CLSPRC": "-", "LIST_SHRS": "1", "MKTCAP": "1"},     # no price
        {"ISU_CD": "12345", "TDD_CLSPRC": "100", "LIST_SHRS": "1", "MKTCAP": "100"},  # bad code
    ])
    s = _Session()
    n, upd, _ = kd.sync_day(s, date(2026, 9, 1), "KOSDAQ")
    assert n == 3 and upd == 1
    assert s.inserted == [{"c": "340570", "p": 30650, "s": 16070120, "m": 492549178000,
                          "o": None, "h": None, "l": None}]
    assert s.update_params["fix"] is False


def test_close_is_replaced_from_the_after_market_start(monkeypatch):
    monkeypatch.setattr(kd, "fetch_daily_trade", lambda m, d: [
        {"ISU_CD": "005930", "TDD_CLSPRC": "188700", "LIST_SHRS": "5846278608", "MKTCAP": "1",
         "TDD_OPNPRC": "180000", "TDD_HGPRC": "196500", "TDD_LWPRC": "179200"}])
    s = _Session()
    kd.sync_day(s, kd.AFTER_MARKET_START, "KOSPI")
    assert (s.inserted[0]["o"], s.inserted[0]["h"], s.inserted[0]["l"]) == (180000, 196500, 179200)
    assert s.update_params["fix"] is True
    assert "close_price = CASE" in s.update_sql and "OFFSET 1 LIMIT 1" in s.update_sql


def test_network_errors_are_retried_but_authorization_is_not(monkeypatch):
    calls = []

    def flaky(m, d):
        calls.append(d)
        if len(calls) < 3:
            raise KrxUnavailable("네트워크 오류: ReadTimeout")
        return [{"ISU_CD": "340570"}]
    monkeypatch.setattr(kd, "fetch_daily_trade", flaky)
    monkeypatch.setattr(kd.time, "sleep", lambda s: None)
    assert kd._fetch_retry("KOSDAQ", "20260901") == [{"ISU_CD": "340570"}]
    assert len(calls) == 3

    def unauthorized(m, d):
        raise KrxUnavailable("서비스 미승인 또는 활용기간 만료")
    monkeypatch.setattr(kd, "fetch_daily_trade", unauthorized)
    try:
        kd._fetch_retry("KOSPI", "20260901")
        raise AssertionError("expected KrxUnavailable")
    except KrxUnavailable:
        pass


def test_weekdays_only():
    assert [d.weekday() for d in kd._weekdays(date(2026, 11, 13), date(2026, 11, 17))] == [4, 0, 1]
