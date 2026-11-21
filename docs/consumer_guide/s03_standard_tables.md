---
section: s03_standard_tables
ord: 30
title: Standardized financials
---
Standard columns (same in all standard objects): balance sheet (total_assets, current_assets, cash, receivables, inventory, ppe, intangibles, total_liabilities, current_liabilities, short_term_debt, long_term_debt, total_equity, controlling_equity, retained_earnings, trade_payables, net_debt, shares_out), income statement (revenue, cogs, gross_profit, sga, rd_expense, operating_income, interest_expense, ebt, tax_expense, net_income, controlling_ni), cash flow (cfo, cfi, cff, capex, dividends_paid), derived (depreciation, amortization, da_total, ebitda, fcf).

Sign conventions (R341, 2026-11-18): `tax_expense` is expense-positive (a tax benefit is negative) whatever sign the filing printed; `ebt`, `net_income` are negative for a loss. `ebt - tax_expense = net_income` holds except when the company has discontinued operations: then `ebt - tax_expense` equals `is.continuing_ni` in `extended_financials`, and `is.discontinued_ni` is the discontinued-operations result (`net_income` = continuing + discontinued). Use them to tell a legitimate gap from a data error.

Debt columns (2026-11-18): `short_term_debt` is only the printed short-term borrowings line (단기차입금) and `long_term_debt` only the long-term borrowings line (장기차입금). Current portion of long-term debt, bonds, convertible / exchangeable / warrant bonds are NOT in either column. For total borrowings or net cash use `net_debt` = (all borrowing lines) - cash; never `short_term_debt + long_term_debt - cash` (measured FY2025 consolidated: different in 1,281 of 2,514 rows, debt understated by more than 10% of liabilities in 755). NULL in `short_term_debt` / `long_term_debt` means that line is not printed, not that the company has no debt. Debt-free companies (R343, 2026-11-18): when neither the balance sheet nor the notes of the filing show any borrowing or bond amount, `net_debt` = -cash while `short_term_debt` / `long_term_debt` stay NULL. `net_debt` NULL now means debt-free could not be confirmed: borrowings may sit inside a catch-all line such as 기타금융부채 (seen only in the notes), the notes are not loaded, or debt was repaid during the period (the notes still show it). Treat NULL as unknown, not as zero debt.

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

One-off non-operating items (R369, 2026-11-21): `extended_financials` has five totals — `is.impairment_loss`, `is.impairment_reversal`, `is.disposal_gain`, `is.disposal_loss`, `is.debt_forgiveness_gain` (KRW, gains and losses both positive). Source order: the income-statement line when the filing prints one, otherwise the sum of the matching lines in the 기타수익·기타비용·금융수익·금융비용 notes. No row means neither names the item (unknown, not zero); a printed 0 stays 0. Disposal items cover non-financial assets (property, plant, equipment, intangibles, investment property, right-of-use assets, subsidiaries / associates / joint ventures, assets held for sale); financial-asset disposal gains and losses, trade receivable impairment / credit loss (대손) and inventory write-downs are excluded. A net label such as `손상차손(환입)` is not split, so it yields no row. Quarter / half-year rows are cumulative like the other flow accounts.
