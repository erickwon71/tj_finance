"""Layer 3 (combination) — assemble std metrics from Layer 2 report_lines.

New chain only. Reads report_lines (raw tree, label_raw) — NOT fact_v2 — and
produces the std value contract (same columns as std_financials_v2). The old
chain's proven resolution heuristics (fin2.standardize.build._resolve /
_reduce_conflict) are ported here, adapted from acode-based signals to
report_lines' label_raw + structural signals (node_role, section_path).
"""
