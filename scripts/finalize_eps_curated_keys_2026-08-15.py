"""
Finalize the curated override key set at the correct granularity:
(rcept_no, statement, basis, table_seq, label_raw) -- narrowed from the design
doc's original rcept_no-only proposal after discovering same-table sibling
clean-EPS-label collisions (see check_rcept_key_granularity_risk_2026-08-15.py).
"""
import json, os
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "eps_curated_candidates_2026-08-15.json")) as f:
    data = json.load(f)

confirmed = data["confirmed"]
likely = data["likely_no_xref"]
all_candidates = confirmed + likely

# final key granularity: (rcept_no, statement, basis, table_seq, label)
final_keys = set()
for r in all_candidates:
    final_keys.add((r["rcept_no"], r["statement"], r["basis"], r["table_seq"], r["label"]))

print(f"CONFIRMED rows: {len(confirmed)}  (cross-validated vs independent std_v3 total)")
print(f"LIKELY rows: {len(likely)}  (headline+embedded-number text signal, 2/2 origin-XML samples verified)")
print(f"combined final label-level keys: {len(final_keys)}")

distinct_rcept = set(k[0] for k in final_keys)
distinct_filings = set((r["corp_code"], r["fy"], r["period"]) for r in all_candidates)
distinct_corps = set(r["corp_code"] for r in all_candidates)

print(f"distinct rcept_no: {len(distinct_rcept)}")
print(f"distinct filings (corp+fy+period): {len(distinct_filings)}")
print(f"distinct corps: {len(distinct_corps)}")

# fy range
fys = sorted(set(r["fy"] for r in all_candidates))
print(f"fiscal year range: {fys[0]}..{fys[-1]}")

# Save the final key set (as a list of tuples, JSON-serializable) for the
# implementation phase.
out_path = os.path.join(_HERE, "eps_curated_final_keys_2026-08-15.json")
with open(out_path, "w") as f:
    json.dump(sorted(final_keys), f, ensure_ascii=False, indent=1)
print(f"\nsaved final keys to {out_path}")
