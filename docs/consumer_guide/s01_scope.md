---
section: s01_scope
ord: 10
title: What this DB is
---
Korean listed companies (KOSPI/KOSDAQ common stock; about 2,540 tickers, 800 KOSPI + 1,731 KOSDAQ active). Source = DART periodic reports (annual / half / quarter) and KRX prices. Maintained by the separate tj_finance project. You have read-only access (role `tja_reader`); never write.

All amounts are KRW (won) as `bigint`. Per-share and ratio values are noted where they differ.

Read this guide first: `SELECT section, title, body FROM consumer_guide ORDER BY ord;`
Per-object notes are in the table/column comments: `\d+ std_financials_v3`, or `obj_description` / `col_description`.

Freshness: `SELECT * FROM load_status;` (R350) — one row per item (`pipeline:full` daily DART run, `filings`, `capital_events`, `stock_prices`, `consumer_guide`) with `last_run_at`, `last_status`, `last_success_at`, `data_through` and `stale` (no new data for more than 4 days; long holidays can set it). Check it at the start of a run: if `capital_events` or `pipeline:full` is stale, share-count corrections after bonus issues may be missing. The `consumer_guide` row carries `version` (= `guide_version`); when it differs from the one you saw last, re-read the guide. `pipeline_runs` holds the run history itself (`status`: running / success / failed / killed / abandoned).
