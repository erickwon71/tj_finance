---
section: s03_standard_tables
ord: 30
title: Standardized financials
---
Standard columns (same in all standard objects): balance sheet (total_assets, current_assets, cash, receivables, inventory, ppe, intangibles, total_liabilities, current_liabilities, short_term_debt, long_term_debt, total_equity, controlling_equity, retained_earnings, trade_payables, net_debt, shares_out), income statement (revenue, cogs, gross_profit, sga, rd_expense, operating_income, interest_expense, ebt, tax_expense, net_income, controlling_ni), cash flow (cfo, cfi, cff, capex, dividends_paid), derived (depreciation, amortization, da_total, ebitda, fcf).

**std_financials_v3** key = (corp_code, fiscal_year, fiscal_period, statement_type).
- fiscal_period is FY, H1, Q1 or Q3 (as reported; there is no Q2/Q4 row).
- Flow items (income statement, cash flow) are **cumulative year-to-date**. Example, 2024 revenue: Q1 71.9T, H1 146.0T, Q3 225.1T, FY 300.9T. Stock items (balance sheet) are period-end balances.
- fiscal_year follows the company's own fiscal year (values up to 2027 exist for non-December year ends).

**std_financials_calendar** (use view `calendar_financials`, which is `version = 1`): calendar aligned.
- calendar_period CQ1..CQ4 = **discrete single quarters** (derived by differencing the cumulative values), CY = calendar year.
- Use this for TTM, QoQ and YoY work.
- `derivation = 'recomposed'` means a non-December fiscal year was recomposed into calendar quarters (about 1% of rows).

**statement_type**: `consolidated` or `separate`. See section s05.

**Quality filter**: always use `data_quality < 3`.
- v3: 1 = ok; 2 = warning (balance sheet identity off by 1-5%, or gross profit inconsistent with revenue - cogs by >5%); 3 = error (identity off by >5% or total assets <= 0), quarantined. Counts: 316,090 / 2,576 / 1,513.
- calendar: 2 = at least one needed flow component is missing in the underlying quarters (99k rows, common), not an error; the calendar value is max over its quarters.

**Variants**
- `standard_financials` = v3 as a view, joined with the independent audit result `gate_b_status` (rows with `fail_a` are removed; `unaudited` rows are kept).
- `standard_financials_verified` = only `gate_b_status = 'pass'`: highest trust, lower coverage.
- `extended_financials` = long format (corp_code, fiscal_year, fiscal_period, basis, canonical_account, amount_won, amount_exact) for accounts that are not standard columns (e.g. lease liabilities, treasury stock). Same cumulative convention as v3. Use `amount_exact` when decimals matter (e.g. EPS).
