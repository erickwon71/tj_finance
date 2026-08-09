"""Layer 2 (transcription) — additional, non-financial-statement report content.

`biz_raw_tables.py` transcribes 'II. 사업의 내용' body tables (production/output/
utilization, sales channel, catalog items, order backlog) losslessly into
`biz_section_tables`, so layer3-equivalent code (collector/biz_metrics.py,
collector/order_backlog.py) never opens a raw report file itself (R1,
docs/plans/biz_content_layer2_migration_2026-08-09.md).

report_lines/note_lines (financial statements + notes) live in
`fin2/extract/report_lines.py`, not here — this package covers the parts of
layer2 that were historically scattered under `fin2/extract/`.
"""
