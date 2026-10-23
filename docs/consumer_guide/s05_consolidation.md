---
section: s05_consolidation
ord: 50
title: Consolidated vs separate
---
Prefer `statement_type = 'consolidated'`; fall back to `separate` only when no consolidated row exists.

`std_financials_v3.consolidation_status` (set on consolidated rows; empty on separate rows):
- `consolidated`: real consolidated statements.
- `no_subsidiary_confirmed`: the company has no subsidiaries (confirmed from the report), so the "consolidated" row equals the separate statements. Safe to use.
- `fallback_unconfirmed`: no consolidated data was found and the separate statements are shown, but it is not confirmed that the company has no subsidiaries. Use with caution; values may understate the group.
`basis_fallback = true` marks a single-basis company filled from the other basis.

Financial-sector firms (`corporations.account_bucket = 'financial'`, about 74 companies) have a different account structure. revenue, cogs and gross_profit are not comparable with industrial companies.
