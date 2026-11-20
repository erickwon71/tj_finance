---
section: s10_structured
ord: 100
title: Structured disclosure tables
---
Beyond the financial statements, the role can read these tables extracted from the same DART reports. They are not covered by the financial-statement verification campaign (parsed text tables), so treat them as less verified than `std_financials_v3` and cross-check important values.

| table | content | key / time columns |
|---|---|---|
| `biz_metrics` | business-section metrics (segment sales, capacity, utilization, R&D ...) long format | corp_code, fiscal_year, metric, segment, item, period_label; check `unit`, `is_ratio` |
| `biz_metrics_periodic` | same as `biz_metrics` for quarterly / half-year reports (segment sales, product sales, production), plus `fiscal_period` (Q1/H1/Q3). The row with `period_year = fiscal_year` is that period (cumulative as printed); other `period_year` rows are the prior full-year columns printed in the same table. Never mix with `biz_metrics` rows | corp_code, fiscal_year, fiscal_period, metric, segment, item, period_year |
| `capital_events` | paid/free increase, reduction, CB issue, treasury acquire/dispose | `filed_at`, `event_type`, `shares_delta`, `detail` (jsonb) |
| `regulatory_events` | trading halt, disclosure violation, delisting, admin issue, rehabilitation; `is_lift` = release | `filed_at`, `event_type` |
| `dividend_facts` | DPS, total dividend, payout ratio, yield | corp_code, fiscal_year |
| `employee_stats` | employees per division/sex, tenure, salary | corp_code, fiscal_year, division, sex |
| `exec_pay_individual`, `exec_pay_summary` | executive pay | corp_code, fiscal_year |
| `executives` | registered/unregistered executives, career, tenure | corp_code, fiscal_year |
| `major_shareholders`, `shareholder_changes`, `retail_ownership` | ownership structure | corp_code, fiscal_year |
| `other_investments` | investments in other corporations | corp_code, fiscal_year |
| `treasury_activity` | treasury-share holdings and movements | corp_code, fiscal_year, stock_kind |
| `order_backlog` | order backlog (only companies that report it). Read `layout` first, see the note below | corp_code, fiscal_year, category, layout |
| `order_backlog_periodic` | `order_backlog` for quarterly / half-year reports, plus `fiscal_period` | corp_code, fiscal_year, fiscal_period, category |
| `report_shares_outstanding` | shares outstanding per report, treasury and float | rcept_no, as_of_date |

- Point in time: a row is public on or after the earliest `filed_at` of its filing (`rcept_no` -> `filings.filed_at`; use the minimum over the same period, see s04). `capital_events` and `regulatory_events` carry `filed_at` themselves.
- Map to a company with `corp_code` (see `corporations`); `fiscal_year` is the company's own fiscal year.
- Amounts are KRW unless a `unit` column says otherwise. `raw` / `detail` jsonb columns keep the source record; do not rely on their shape.
- Rows may be missing for companies or years where the report did not disclose the item; absence is not zero.
- `capital_events` and `regulatory_events` come from the DART disclosure API; the other tables are parsed from the report documents.
- `biz_metrics` / `biz_metrics_periodic` rows with `metric = 'sales'` are sales amounts only (R348/R349, 2026-11-19): share (비중/비율), profit and asset columns, and quantity columns of quantity/amount pairs are not loaded; `unit` is the money unit of the table caption. `period_year` is read from 제N기, years, and 당기/전기/전전기 headers; it stays NULL only when the table prints no period. The same table can still carry channel rows (수출/내수/합계) and segment/item rows side by side — pick one level, do not add them all.
- `order_backlog` / `order_backlog_periodic` columns depend on `layout` (R347, 2026-11-19). All amounts are in `unit` as printed.
  - `cumulative` (수주총액 | 기납품액 | 수주잔고): `contract_total` = contract amount to date, `completed` = delivered/recognised to date, `backlog_amt` = backlog. `opening_backlog` and `new_orders` are NULL.
  - `rollforward` (기초잔고 | 신규 | 매출인식 | 기말잔고): `opening_backlog`, `new_orders` = period inflow (new orders plus printed amendments, FX, cancellations), `completed` = recognised in the period (positive), `backlog_amt` = ending. `contract_total` is NULL. `opening_backlog + new_orders - completed = backlog_amt` holds for about 93% of complete rows; the rest do not add up in the report itself.
  - `scope_change` (R362, 2026-11-21, rollforward only): backlog that came in or left with a change of the group — business combination, merger, disposal of a subsidiary — with the printed sign. It is not part of `new_orders`; when it is set, `opening_backlog + new_orders + scope_change - completed = backlog_amt`. NULL when the table prints no such column (almost always). Example: HD현대중공업 FY2025 `scope_change` = 11,376,357 (HD현대미포 merger), `new_orders` = 11,500,524.
  - Before R347 `new_orders` held the contract amount of cumulative tables; that value is now `contract_total`.
  - A table may carry a total row (`category` such as `합계`, `합 계`) next to its segment rows; do not add both. Detail tables with more than 10 project rows are collapsed to one row with `category` NULL; so are tables whose rows repeat the same label (separate contracts of one item) when the table prints a total row — that row is used as printed (R365, 2026-11-21).
