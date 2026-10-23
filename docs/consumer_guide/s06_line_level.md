---
section: s06_line_level
ord: 60
title: Line items (report_lines_l3)
---
One row per printed cell of a financial statement.

Main columns: rcept_no, corp_code, report_fiscal_year, report_fiscal_period, statement (BS / IS / CF / SCE), basis (consolidated / separate), section_path, row_order, depth, label_raw (account label as printed, may include note numbers like "(주29)"), col_index, col_label, context_fiscal_year, period_kind, is_cumulative, value_won, printed_value_won, correction_rule, node_role, value_raw.

Rules:
- Restrict to final filings and pass rcept_no as an array: `rcept_no = ANY(ARRAY(SELECT rcept_no FROM filings WHERE corp_code = ... AND is_final AND ...))`. **Do not join the view to `filings`**: the planner scans all of report_lines (26 GB).
- Amendments replace originals only if you filter `is_final`; otherwise the same cell appears once per version.
- Use this level only for items that are not in the standard columns; for normal metrics use the standard tables.
- `value_won` can be NULL where the printed cell was unreadable (the original text is in `value_raw`).
