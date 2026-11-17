---
section: s07_prices
ord: 70
title: Prices and valuation
---
**stock_prices** (stock_code, trade_date), 1990-01-03 to today, one row per ticker per trading day: open/high/low/close_price (KRW, integer), volume, market_cap (KRW), shares_out, and KRX-published per, pbr, eps, bps, dps, div_yield.
- `close_price` is the **adjusted** close (splits and bonus issues back-adjusted). Use it for charts and returns.
- Since 2026-09-14 (KRX after-market until 20:00) `close_price` from the daily OHLCV source is the last trade of the day, which often differs from the regular-session close `close_raw` (15:30). Use `close_raw` for the official close.
- `close_raw` is the **unadjusted** close of the day and `list_shares` the listed common shares of the day (treasury included), both from KRX daily trade data, 2015 onward. `krx_mktcap` is KRX's own market cap (close_raw x list_shares).
- `shares_out` is the **float** share count of the day: list_shares x the float ratio (float shares / common shares) of the latest report on or before that day, so splits and reverse splits inside a quarter scale the treasury part too. `market_cap` = close_raw x shares_out. It changes on the day a share change is reflected by KRX (bonus issues: when the new shares are listed, usually 2-3 weeks after the ex-rights date, as in KRX's own figure).
- Before 2015 (no KRX daily data) market_cap / shares_out use close_price x the latest reported float shares and are approximate.
Map tickers to financials via `corporations` (stock_code <-> corp_code). Prices use stock_code; financials use corp_code.

**valuation_daily** (materialized view, active companies only): per, pbr, psr, pcr, ev, ev_ebitda, ev_ebit, eps, bps, dps, dividend_yield per (stock_code, trade_date), computed from market_cap and the most recent annual (`FY`) row of `std_financials_v3` with `period_end <= trade_date`.
Caveats:
- It uses **annual** values, not TTM.
- It is **not point-in-time**: the annual report is used from its period end, but it is only disclosed about 2-3 months later. Do not use it for backtests; build your own from `std_financials_calendar` plus `filings.filed_at`.
- A ratio is NULL when its denominator is <= 0 (loss-making, negative equity).
- dps and dividend_yield are derived from cash-flow dividends paid (dividend_yield = dividends / market_cap), so they are approximations.
- It is refreshed by tj_finance; check `max(trade_date)` before relying on it.
