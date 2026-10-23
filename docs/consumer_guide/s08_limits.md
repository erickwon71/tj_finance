---
section: s08_limits
ord: 80
title: Known gaps
---
- 462 filings (2015 and later) exist only as PDF and are parked; some periods of those companies may be missing.
- Data before 2015 is thinner and less verified than 2015 and later (older report formats). Treat pre-2015 values with more caution.
- Foreign companies (stock_code starting with 9) are excluded.
- Delisted companies keep their history (`corporations.is_active = false`), but not every delisted company ever listed is present.
- Financial-sector firms use a different account structure (see s05).
- Quarterly values: Q2 and Q4 are not reported separately; they exist only as discrete values in `std_financials_calendar` (CQ2, CQ4), derived by differencing.
- `shares_out` is filled for about 95% of 2015+ rows; check for NULL.
- Do not patch data locally. Report suspected errors to the tj_finance owner with the rcept_no and cell.
