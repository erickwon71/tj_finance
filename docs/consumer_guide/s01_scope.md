---
section: s01_scope
ord: 10
title: What this DB is
---
Korean listed companies (KOSPI/KOSDAQ common stock; about 2,540 tickers, 800 KOSPI + 1,731 KOSDAQ active). Source = DART periodic reports (annual / half / quarter) and KRX prices. Maintained by the separate tj_finance project. You have read-only access (role `tja_reader`); never write.

All amounts are KRW (won) as `bigint`. Per-share and ratio values are noted where they differ.

Read this guide first: `SELECT section, title, body FROM consumer_guide ORDER BY ord;`
Per-object notes are in the table/column comments: `\d+ std_financials_v3`, or `obj_description` / `col_description`.
