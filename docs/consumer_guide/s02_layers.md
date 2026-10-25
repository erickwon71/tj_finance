---
section: s02_layers
ord: 20
title: Which layer to use
---
The data is built in layers. Use only the refined (layer 3) objects.

- Layer 2 `report_lines` (26 GB) holds printed values only, unrefined (wrong signs, unit slips and source defects are kept as printed). The read-only role has **no access** to it (permission denied); use layer 3 instead.
- Layer 3 is refined:
  - line level: `report_lines_l3` (view = layer 2 plus tj_finance corrections)
  - standardized metrics: `std_financials_v3`, `standard_financials`, `standard_financials_verified`, `std_financials_calendar` / `calendar_financials`, `extended_financials`
- In `report_lines_l3`: `printed_value_won` is the original printed number, `value_won` is the corrected value, `correction_rule` says why they differ (NULL = no correction).
- `note_lines` (94 GB, footnote/notes lines) is layer 2 quality: printed values only, **not refined and not yet verified**. The verification campaign has deferred it, and there is no layer 3 view for it (corrections in `layer3_cell_corrections` cover only BS/IS/CF/SCE). The role has no access to it. Values derived from notes that matter for analysis (depreciation, amortization, D&A, EBITDA) are already in `std_financials_v3` and `extended_financials`.
- Other tables (`report_tables`, `face_audit*`, `*_snap_*`, `layer2_review_queue`, `verification_results`, ...) are internal working data and are not readable by the role.
