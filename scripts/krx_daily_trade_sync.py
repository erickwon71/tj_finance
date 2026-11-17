"""KRX OpenAPI daily trade -> stock_prices.close_raw / list_shares / krx_mktcap (2026-11-17).

One call per market per weekday (stk_bydd_trd, ksq_bydd_trd) returns every listed issue's
unadjusted close, listed shares and KRX market cap of that day. Only existing stock_prices rows
(stock_code, trade_date) are updated; rows KRX has but stock_prices lacks are counted, not
inserted (close_price, the adjusted series, would be unknown).

From 2026-09-14 (KRX after-market until 20:00) open/high/low/close are also replaced by the
regular-session values, scaled to the stored adjusted basis (see _UPDATE_SQL).

Fetched (date, market) pairs are logged in public.krx_daily_trade_log, including empty answers
(holidays), so a long backfill can be resumed: --resume skips logged pairs.

usage:
  python scripts/krx_daily_trade_sync.py --start 20150101 --resume     # backfill
  python scripts/krx_daily_trade_sync.py --days 15                       # nightly top-up
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.krx_client import DAILY_TRADE_ENDPOINTS, KrxUnavailable, fetch_daily_trade

# KRX after-market (16:00-20:00, all stocks) opened on this day; since then the pykrx daily close is
# the last trade of the day, not the regular-session close (R333, found 2026-11-18).
AFTER_MARKET_START = date(2026, 9, 14)

_LOG_DDL ="""CREATE TABLE IF NOT EXISTS public.krx_daily_trade_log (
    bas_dd date, market text, n_rows integer, n_updated integer, n_missing integer,
    fetched_at timestamp DEFAULT now(), PRIMARY KEY (bas_dd, market))"""


# From AFTER_MARKET_START the OHLCV source mixes sessions: open and volume are regular-session values,
# high/low may include the after-market and close is the after-market last trade. Replace open/high/
# low/close with KRX regular-session values on the stored (adjusted) basis. The basis factor is the
# median of stored/KRX over open, high and low: open is never touched by the after-market, so the
# median is the true factor (1 without a later corporate action, the adjustment ratio otherwise).
# Rows without a KRX high (trading halts) keep their values (close = reference price already).
_UPDATE_SQL = """
UPDATE stock_prices sp SET close_raw = k.p, list_shares = k.s, krx_mktcap = k.m,
    open_price  = CASE WHEN k.r IS NULL THEN sp.open_price  ELSE round(k.o * k.r)::integer END,
    high_price  = CASE WHEN k.r IS NULL THEN sp.high_price  ELSE round(k.h * k.r)::integer END,
    low_price   = CASE WHEN k.r IS NULL THEN sp.low_price   ELSE round(k.l * k.r)::integer END,
    close_price = CASE WHEN k.r IS NULL THEN sp.close_price ELSE round(k.p * k.r)::integer END
FROM (
    SELECT k.*,
           CASE WHEN :fix AND k.o > 0 AND k.h > 0 AND k.l > 0
                     AND s.open_price > 0 AND s.high_price > 0 AND s.low_price > 0
                THEN (SELECT x FROM unnest(ARRAY[s.open_price::numeric / k.o, s.high_price::numeric / k.h,
                                                 s.low_price::numeric / k.l]) x ORDER BY x OFFSET 1 LIMIT 1)
           END AS r
    FROM _krx_day k JOIN stock_prices s ON s.stock_code = k.c AND s.trade_date = :d
) k
WHERE sp.stock_code = k.c AND sp.trade_date = :d"""


def _int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _fetch_retry(market: str, bas_dd: str, attempts: int = 6) -> list[dict]:
    """Network errors / timeouts are retried with a growing pause; authorization errors are not."""
    for i in range(attempts):
        try:
            return fetch_daily_trade(market, bas_dd)
        except KrxUnavailable as exc:
            transient = any(k in str(exc) for k in ("네트워크", "JSON 파싱 실패", "HTTP 5"))
            if not transient or i == attempts - 1:
                raise
            logger.warning(f"[krx-daily] {market} {bas_dd} 재시도 {i + 1}: {exc}")
            time.sleep(5 * (i + 1))
    return []


def sync_day(session, d: date, market: str) -> tuple[int, int, int]:
    rows = _fetch_retry(market, d.strftime("%Y%m%d"))
    recs = []
    for r in rows:
        code = (r.get("ISU_CD") or "").strip()
        close, shares, cap = _int(r.get("TDD_CLSPRC")), _int(r.get("LIST_SHRS")), _int(r.get("MKTCAP"))
        if len(code) == 6 and close and shares:
            recs.append({"c": code, "p": close, "s": shares, "m": cap, "o": _int(r.get("TDD_OPNPRC")),
                         "h": _int(r.get("TDD_HGPRC")), "l": _int(r.get("TDD_LWPRC"))})
    n_upd = n_miss = 0
    if recs:
        session.execute(text("CREATE TEMP TABLE IF NOT EXISTS _krx_day (c varchar(6), p integer, s bigint, "
                             "m bigint, o integer, h integer, l integer) ON COMMIT DELETE ROWS"))
        session.execute(text("INSERT INTO _krx_day VALUES (:c, :p, :s, :m, :o, :h, :l)"), recs)
        n_upd = session.execute(text(_UPDATE_SQL), {"d": d, "fix": d >= AFTER_MARKET_START}).rowcount
        n_miss = session.execute(text("""
            SELECT count(*) FROM _krx_day k WHERE NOT EXISTS
              (SELECT 1 FROM stock_prices sp WHERE sp.stock_code = k.c AND sp.trade_date = :d)"""),
            {"d": d}).scalar()
    session.execute(text("""
        INSERT INTO public.krx_daily_trade_log (bas_dd, market, n_rows, n_updated, n_missing, fetched_at)
        VALUES (:d, :mk, :n, :u, :x, now())
        ON CONFLICT (bas_dd, market) DO UPDATE SET n_rows = EXCLUDED.n_rows, n_updated = EXCLUDED.n_updated,
            n_missing = EXCLUDED.n_missing, fetched_at = now()"""),
        {"d": d, "mk": market, "n": len(rows), "u": n_upd, "x": n_miss})
    return len(rows), n_upd, n_miss


def run(start: date, end: date, resume: bool = False, sleep: float = 0.05) -> dict:
    out = {"days": 0, "calls": 0, "updated": 0, "missing": 0}
    with get_session() as s:
        s.execute(text(_LOG_DDL))
        s.commit()
        done = set()
        if resume:
            done = {(r[0], r[1]) for r in s.execute(text(
                "SELECT bas_dd, market FROM public.krx_daily_trade_log WHERE bas_dd BETWEEN :a AND :b"),
                {"a": start, "b": end})}
        for d in _weekdays(start, end):
            for market in DAILY_TRADE_ENDPOINTS:
                if (d, market) in done:
                    continue
                n, u, x = sync_day(s, d, market)
                s.commit()
                out["calls"] += 1
                out["updated"] += u
                out["missing"] += x
                time.sleep(sleep)
            out["days"] += 1
            if out["days"] % 50 == 0:
                logger.info(f"[krx-daily] {d} 까지 — 호출 {out['calls']} · 갱신 {out['updated']:,}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYYMMDD")
    ap.add_argument("--end", help="YYYYMMDD (default: yesterday)")
    ap.add_argument("--days", type=int, help="look back this many calendar days from yesterday")
    ap.add_argument("--resume", action="store_true", help="skip (date, market) pairs already logged")
    args = ap.parse_args()
    end = (datetime.strptime(args.end, "%Y%m%d").date() if args.end
           else date.today() - timedelta(days=1))
    if args.start:
        start = datetime.strptime(args.start, "%Y%m%d").date()
    else:
        start = end - timedelta(days=(args.days or 15))
    try:
        out = run(start, end, resume=args.resume)
    except KrxUnavailable as exc:
        logger.error(f"[krx-daily] 중단 — {exc}")
        sys.exit(2)
    logger.info(f"[krx-daily] 완료 {start}~{end} — {out}")


if __name__ == "__main__":
    main()
