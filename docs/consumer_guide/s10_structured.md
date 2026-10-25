---
section: s10_structured
ord: 100
title: Structured disclosure tables
---
Beyond the financial statements, the role can read these tables extracted from the same DART reports. They are not covered by the financial-statement verification campaign (parsed text tables), so treat them as less verified than `std_financials_v3` and cross-check important values.

| table | content | key / time columns |
|---|---|---|
| `biz_metrics` | business-section metrics (segment sales, capacity, utilization, R&D ...) long format | corp_code, fiscal_year, metric, segment, item, period_label; check `unit`, `is_ratio` |
| `capital_events` | paid/free increase, reduction, CB issue, treasury acquire/dispose | `filed_at`, `event_type`, `shares_delta`, `detail` (jsonb) |
| `regulatory_events` | trading halt, disclosure violation, delisting, admin issue, rehabilitation; `is_lift` = release | `filed_at`, `event_type` |
| `dividend_facts` | DPS, total dividend, payout ratio, yield | corp_code, fiscal_year |
| `employee_stats` | employees per division/sex, tenure, salary | corp_code, fiscal_year, division, sex |
| `exec_pay_individual`, `exec_pay_summary` | executive pay | corp_code, fiscal_year |
| `executives` | registered/unregistered executives, career, tenure | corp_code, fiscal_year |
| `major_shareholders`, `shareholder_changes`, `retail_ownership` | ownership structure | corp_code, fiscal_year |
| `other_investments` | investments in other corporations | corp_code, fiscal_year |
| `treasury_activity` | treasury-share holdings and movements | corp_code, fiscal_year, stock_kind |
| `order_backlog` | order backlog (only companies that report it) | corp_code, fiscal_year, category |
| `report_shares_outstanding` | shares outstanding per report, treasury and float | rcept_no, as_of_date |

- Point in time: a row is public on or after the earliest `filed_at` of its filing (`rcept_no` -> `filings.filed_at`; use the minimum over the same period, see s04). `capital_events` and `regulatory_events` carry `filed_at` themselves.
- Map to a company with `corp_code` (see `corporations`); `fiscal_year` is the company's own fiscal year.
- Amounts are KRW unless a `unit` column says otherwise. `raw` / `detail` jsonb columns keep the source record; do not rely on their shape.
- Rows may be missing for companies or years where the report did not disclose the item; absence is not zero.
- `capital_events` and `regulatory_events` come from the DART disclosure API; the other tables are parsed from the report documents.
