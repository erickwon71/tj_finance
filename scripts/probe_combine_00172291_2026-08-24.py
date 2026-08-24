"""Root-cause probe for the new Gate B regression found in the 2026-08-24 full
re-audit: 00172291(더존비즈온) 2025 H1 consolidated controlling_ni.

db_won=11,111,394,247 vs report_won=29,698,844,769 (net_income db_won=29,582,558,149,
close to report controlling_ni but not equal).

Reproduces the real build_std_v3.py::build_corp() call shape (merged computed once,
combine_full(..., merged=merged)) — NOT the earlier mismatched probe pattern from
scripts/phase0_probe_combine_2026-08-23.py that didn't match std_v3 for 01497869.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.db import get_session
from fin2.layer3.combine import combine_full, build_merged_lines, _map_rows

corp, fy, period, basis = "00172291", 2025, "H1", "consolidated"

with get_session() as session:
    merged = build_merged_lines(session, corp, fy, period)
    print(f"merged lines: {len(merged) if merged else 0}")

    cands = _map_rows(merged, period, basis, ("BS", "IS", "CF"), corp=corp, fy=fy)
    print("\n=== is.net_income candidates (full dict) ===")
    for c in cands.get("is.net_income", []):
        print(" ", c)
    print("\n=== is.controlling_ni candidates (full dict) ===")
    for c in cands.get("is.controlling_ni", []):
        print(" ", c)
    print("\n=== is.noncontrolling_ni candidates (full dict) ===")
    for c in cands.get("is.noncontrolling_ni", []):
        print(" ", c)

    col, conflicts, prov = combine_full(session, corp, fy, period, basis, merged=merged)
    print("\n=== resolved net_income ===", col.get("net_income"))
    print("=== resolved controlling_ni ===", col.get("controlling_ni"))
    print("=== resolved noncontrolling_ni ===", col.get("noncontrolling_ni"))
    print("=== conflicts on is.net_income ===", conflicts.get("is.net_income"))
    print("=== conflicts on is.controlling_ni ===", conflicts.get("is.controlling_ni"))
    print("=== conflicts on is.noncontrolling_ni ===", conflicts.get("is.noncontrolling_ni"))
