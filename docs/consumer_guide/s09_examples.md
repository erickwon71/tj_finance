---
section: s09_examples
ord: 90
title: Verified example queries
---
All four were executed with role tja_reader on 2026-10-23. Replace '005930' with the ticker.

1. Latest 4 discrete quarters (consolidated):
```sql
SELECT c.calendar_year, c.calendar_period, c.revenue, c.net_income, c.data_quality
FROM std_financials_calendar c JOIN corporations co USING (corp_code)
WHERE co.stock_code = '005930' AND c.version = 1
  AND c.statement_type = 'consolidated' AND c.calendar_period LIKE 'CQ%'
ORDER BY c.calendar_year DESC, c.calendar_period DESC LIMIT 4;
```

2. Point-in-time: quarters public as of 2025-06-30 (availability = earliest filing date):
```sql
WITH avail AS (
  SELECT corp_code, period_end_date, min(filed_at) AS filed_at
  FROM filings
  WHERE corp_code = (SELECT corp_code FROM corporations WHERE stock_code = '005930')
    AND period_end_date IS NOT NULL
  GROUP BY 1, 2)
SELECT c.calendar_year, c.calendar_period, c.revenue, a.filed_at
FROM std_financials_calendar c
JOIN avail a ON a.corp_code = c.corp_code AND a.period_end_date = c.period_end
WHERE c.version = 1 AND c.statement_type = 'consolidated'
  AND c.calendar_period LIKE 'CQ%' AND c.data_quality < 3
  AND a.filed_at <= DATE '2025-06-30'
ORDER BY c.period_end DESC LIMIT 4;
```

3. Latest price and valuation (annual basis, not point-in-time):
```sql
SELECT trade_date, close_price, market_cap, per, pbr, fiscal_year, basis
FROM valuation_daily WHERE stock_code = '005930'
ORDER BY trade_date DESC LIMIT 2;
```

4. Line items of one final report (array pattern, no join to filings):
```sql
SELECT statement, label_raw, value_won, printed_value_won, correction_rule
FROM report_lines_l3
WHERE rcept_no = ANY(ARRAY(
        SELECT rcept_no FROM filings
        WHERE corp_code = (SELECT corp_code FROM corporations WHERE stock_code = '005930')
          AND is_final AND fiscal_year = 2024 AND fiscal_period = 'FY'))
  AND basis = 'consolidated' AND statement = 'IS' AND depth <= 1
ORDER BY row_order, col_index LIMIT 6;
```
