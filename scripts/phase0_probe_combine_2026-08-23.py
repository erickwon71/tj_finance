"""Phase 0 (bug 2) deep-dive: run fin2/layer3/combine.py::combine_full() directly
for 01497869 2025 Q1 consolidated and inspect the is.net_income candidate pool
(cands) + conflicts dict, to see exactly why the depth=2 attributable row wins
over the depth=0 total row."""
from collector.db import get_session
from fin2.layer3.combine import combine_full, build_merged_lines, _map_rows

corp, fy, period, basis = "01497869", 2025, "Q1", "consolidated"

with get_session() as session:
    merged = build_merged_lines(session, corp, fy, period)
    cands = _map_rows(merged, period, basis, ("BS", "IS", "CF"), corp=corp, fy=fy)
    print("=== is.net_income candidates ===")
    for c in cands.get("is.net_income", []):
        print(" ", {k: c.get(k) for k in ("basis", "value_won", "depth", "section_path",
                                            "label_raw", "stage", "table_seq", "node_role")})
    print("=== is.controlling_ni candidates ===")
    for c in cands.get("is.controlling_ni", []):
        print(" ", {k: c.get(k) for k in ("basis", "value_won", "depth", "section_path",
                                            "label_raw", "stage", "table_seq", "node_role")})

    col, conflicts, prov = combine_full(session, corp, fy, period, basis)
    print("\n=== resolved net_income ===", col.get("is.net_income"))
    print("=== resolved controlling_ni ===", col.get("is.controlling_ni"))
    print("=== conflicts on is.net_income ===", conflicts.get("is.net_income"))
