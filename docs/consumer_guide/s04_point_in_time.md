---
section: s04_point_in_time
ord: 40
title: Avoiding look-ahead bias
---
A period's numbers are public only from the disclosure date. `filings.filed_at` is that date.

- Availability date of a period = `min(filed_at)` over `filings` rows with the same corp_code and `period_end_date = period_end` (see example s09-2).
- `std_financials_calendar` / `std_financials_v3` carry no filing date; join `filings` on (corp_code, period_end_date). If no filing matches, assume a conservative lag (for example 100 days after period end).
- Amendments: `filings.is_amendment`, `superseded_by`, `is_final`. The standard tables already contain the **final (corrected)** values. A backtest therefore sees corrected numbers earlier than the market did; accept this or check `std_financials_v3.amended_cols` / `amend_chain`.
- `valuation_daily` is NOT point-in-time (see s07).
- The universe contains delisted names (`corporations.is_active = false`), so a backtest on the full table is not survivorship-free by default; the DB itself holds survivors plus the delisted names it has history for.
