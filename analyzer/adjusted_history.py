"""R338 - adjusted price history re-based in one piece per stock.

`stock_prices.close_price` is an adjusted series (splits / bonus issues back-adjusted as of the
fetch). The nightly job re-fetches only the last 15 days, so after a corporate action the window
moves to the new basis while older rows keep the old one: a jump that never happened
(코나아이 052400 2026-10-13 33,300 -> 10-14 22,733 while the real close went 33,300 -> 34,000).

Detection: the basis factor F = close_price / close_raw (close_raw = KRX unadjusted close, 2015+,
2010+ after the R338 KRX back-fill) changes on two kinds of days:
  - a real ex-date: the raw close jumps and the adjusted close is continuous;
  - a stale boundary (this defect): the adjusted close jumps and the raw close is continuous.

Repair: re-fetch the whole adjusted history of the stock from Naver siseJson (listing date to
today; pykrx returns the identical values from 2014-08 on, measured 2026-11-18 on 052400: 2,785
common days, 0 differences) and rewrite open/high/low/close of the EXISTING rows only (no new
dates, volume untouched). Rows from AFTER_MARKET_START on carry KRX regular-session values on the
stored basis (krx_daily_trade_sync); they are re-based with the new factor instead of taking the
after-market close of the source.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import text

AFTER_MARKET_START = date(2026, 9, 14)

# Halt days (volume 0) are left out: during a reverse-split halt KRX keeps the old close while the
# source already prices the halt days on the new basis (047400 2026-11-02: adjusted 3,730, raw 746);
# comparing traded days only puts that step on the relisting day, where the raw close jumps.
# A step of the basis factor below this is noise (integer rounding of low adjusted prices is
# handled separately by the per-row bound in _STALE_SQL).
MIN_STEP = 0.01

_STALE_SQL = """
WITH x AS (
  SELECT stock_code, trade_date, close_price, close_raw,
         lag(close_price) OVER w AS pc, lag(close_raw) OVER w AS pr
  FROM stock_prices
  WHERE {where} AND COALESCE(volume, 1) > 0
  WINDOW w AS (PARTITION BY stock_code ORDER BY trade_date))
SELECT stock_code, trade_date,
       ln((close_price::numeric / close_raw) / (pc::numeric / pr)) AS step
FROM x
WHERE pc > 0 AND pr > 0 AND close_raw > 0 AND close_price > 0
  AND abs(ln((close_price::numeric / close_raw) / (pc::numeric / pr)))
      > GREATEST(:min_step, 1.5 / LEAST(close_price, pc))
  AND abs(ln(close_price::numeric / pc)) > abs(ln(close_raw::numeric / pr))
  AND trade_date >= :since
ORDER BY stock_code, trade_date
"""


def stale_boundaries(session, since: date = date(1990, 1, 1),
                     codes: Optional[Iterable[str]] = None) -> list[tuple[str, date, float]]:
    """(stock_code, trade_date, log step) of every stale basis boundary on or after `since`."""
    params: dict = {"min_step": MIN_STEP, "since": since}
    where = "trade_date >= CAST(:since AS date) - 10"
    if codes is not None:
        params["codes"] = list(codes)
        where += " AND stock_code = ANY(:codes)"
    rows = session.execute(text(_STALE_SQL.format(where=where)), params).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def _ratio(new: Optional[int], raw: Optional[float]) -> Optional[float]:
    if not new or not raw or raw <= 0:
        return None
    return new / raw


def rebase_after_market_row(old: dict, new: dict) -> Optional[dict]:
    """New OHLC of a row from AFTER_MARKET_START on.

    The stored row holds KRX regular-session values x old factor (close = close_raw x old_r), so
    the raw regular-session open/high/low are old_x / old_r. The new factor is the median of
    new/raw over open, high and low (open is never touched by the after-market) - the same rule
    as krx_daily_trade_sync._UPDATE_SQL. Returns None when the row cannot be re-based (no KRX
    close, halt): the caller keeps the stored values."""
    raw_close = old.get("close_raw")
    if not raw_close or not old.get("close") or raw_close <= 0:
        return None
    old_r = old["close"] / raw_close
    ratios = [_ratio(new.get(k), (old.get(k) or 0) / old_r) for k in ("open", "high", "low")]
    ratios = [r for r in ratios if r]
    if len(ratios) < 3:
        return None
    r = median(ratios)
    return {k: int(round((old[k] / old_r) * r)) for k in ("open", "high", "low")} | {
        "close": int(round(raw_close * r))}


def plan_rows(old_rows: dict, fetched: list[dict]) -> list[dict]:
    """Rows to write: existing dates only, OHLC only. old_rows: date -> {open, high, low, close,
    close_raw}; fetched: [{dt, open, high, low, close}] from the source."""
    out = []
    for f in fetched:
        old = old_rows.get(f["dt"])
        if old is None:
            continue  # no new dates
        if f["dt"] >= AFTER_MARKET_START:
            new = rebase_after_market_row(old, f)
            if new is None:
                continue
        else:
            new = {k: f.get(k) for k in ("open", "high", "low", "close")}
            if not new["close"]:
                continue
        if any(new[k] != old.get(k) for k in ("open", "high", "low", "close")):
            out.append({"dt": f["dt"], **new})
    return out


_UPDATE = """
UPDATE stock_prices SET open_price = :open, high_price = :high, low_price = :low,
       close_price = :close
WHERE stock_code = :code AND trade_date = :dt"""


def refetch_stock(code: str, today: Optional[date] = None, fetch=None) -> dict:
    """Re-base one stock's whole adjusted history. Commits only when the stock has no more stale
    boundaries than before (the source can carry its own glitches); otherwise rolls back."""
    from collector.db import get_session
    if fetch is None:
        from analyzer.price_fetcher import fetch_naver_daily as fetch
    today = today or date.today()
    fetched = fetch(code, "19900101", today.strftime("%Y%m%d"))
    if not fetched:
        return {"code": code, "status": "no_source", "updated": 0}
    with get_session() as s:
        old_rows = {r[0]: {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "close_raw": r[5]}
                    for r in s.execute(text(
                        "SELECT trade_date, open_price, high_price, low_price, close_price, close_raw "
                        "FROM stock_prices WHERE stock_code = :c"), {"c": code})}
        before = len(stale_boundaries(s, codes=[code]))
        rows = plan_rows(old_rows, fetched)
        if not rows:
            return {"code": code, "status": "unchanged", "updated": 0, "stale_before": before,
                    "stale_after": before}
        s.execute(text(_UPDATE), [{"code": code, **r} for r in rows])
        after = len(stale_boundaries(s, codes=[code]))
        if after > before:
            s.rollback()
            logger.warning(f"[adj-history] {code}: stale {before} -> {after} after re-fetch, rolled back")
            return {"code": code, "status": "rolled_back", "updated": 0, "stale_before": before,
                    "stale_after": after}
        s.commit()
    return {"code": code, "status": "updated", "updated": len(rows), "stale_before": before,
            "stale_after": after}


def nightly(today: Optional[date] = None, lookback_days: int = 20, max_stocks: int = 30,
            sleep: float = 0.4) -> dict:
    """①-c: stocks with a stale boundary in the last `lookback_days` get their whole history
    re-fetched (at most `max_stocks` a night; the rest wait for the next night)."""
    import time
    from collector.db import get_session
    today = today or date.today()
    with get_session() as s:
        hits = stale_boundaries(s, since=today - timedelta(days=lookback_days))
    codes = sorted({h[0] for h in hits})
    out = {"detected": len(codes), "updated": 0, "rolled_back": 0, "unchanged": 0, "no_source": 0,
           "deferred": max(0, len(codes) - max_stocks)}
    for i, code in enumerate(codes[:max_stocks]):
        try:
            res = refetch_stock(code, today)
            out[res["status"]] = out.get(res["status"], 0) + 1
        except Exception as e:  # noqa: BLE001 - per-stock isolation
            out["error"] = out.get("error", 0) + 1
            logger.warning(f"[adj-history] {code} failed: {type(e).__name__}: {e}")
        if sleep and i + 1 < min(len(codes), max_stocks):
            time.sleep(sleep)
    return out


def step_is_stale(pc: float, c: float, pr: float, r: float, min_step: float = MIN_STEP) -> bool:
    """Python mirror of the _STALE_SQL predicate (tests)."""
    step = abs(math.log((c / r) / (pc / pr)))
    return (step > max(min_step, 1.5 / min(c, pc))
            and abs(math.log(c / pc)) > abs(math.log(r / pr)))
