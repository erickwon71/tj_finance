---
section: s07_prices
ord: 70
title: Prices and valuation
---
**stock_prices** (stock_code, trade_date), 1990-01-03 to today, one row per ticker per trading day: open/high/low/close_price (KRW, integer), volume, market_cap (KRW), shares_out (listed shares), and KRX-published per, pbr, eps, bps, dps, div_yield.
Map tickers to financials via `corporations` (stock_code <-> corp_code). Prices use stock_code; financials use corp_code.

**valuation_daily** (materialized view, active companies only): per, pbr, psr, pcr, ev, ev_ebitda, ev_ebit, eps, bps, dps, dividend_yield per (stock_code, trade_date), computed from market_cap and the most recent annual (`FY`) row of `std_financials_v3` with `period_end <= trade_date`.
Caveats:
- It uses **annual** values, not TTM.
- It is **not point-in-time**: the annual report is used from its period end, but it is only disclosed about 2-3 months later. Do not use it for backtests; build your own from `std_financials_calendar` plus `filings.filed_at`.
- A ratio is NULL when its denominator is <= 0 (loss-making, negative equity).
- dps and dividend_yield are derived from cash-flow dividends paid divided by shares, so they are approximations.
- It is refreshed by tj_finance; check `max(trade_date)` before relying on it.
