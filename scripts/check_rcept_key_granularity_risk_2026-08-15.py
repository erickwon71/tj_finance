"""
Check whether the proposed rcept_no-level override key is too coarse: does any
CONFIRMED/LIKELY filing's (rcept_no, statement, basis, table_seq) ALSO contain
a separate, genuine short EPS row (no embedded number/headline pattern) that
lacks its own unit declaration -- which would incorrectly get swept into the
table-unit rescale too if the override key is rcept_no-only.
"""
import sys, os, re, json
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import psycopg2
from parser.common.amount_normalizer import detect_unit_declaration
from fin2.extract.units import ColumnUnits, FX_ONLY

conn = psycopg2.connect(dbname="tj_finance")
cur = conn.cursor()

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "eps_curated_candidates_2026-08-15.json")) as f:
    data = json.load(f)

candidates = data["confirmed"] + data["likely_no_xref"]
keys = set((r["rcept_no"], r["statement"], r["basis"], r["table_seq"]) for r in candidates)
candidate_labels_by_key = {}
for r in candidates:
    k = (r["rcept_no"], r["statement"], r["basis"], r["table_seq"])
    candidate_labels_by_key.setdefault(k, set()).add(r["label"])

print(f"distinct (rcept,statement,basis,table_seq) keys in candidate set: {len(keys)}")

# For each key, fetch ALL section_path='주당손익' rows (row_order IS NULL) in
# that exact table, and check for any OTHER label not in our candidate set.
rcepts = tuple(sorted(set(k[0] for k in keys)))
cur.execute("""
    SELECT rcept_no, statement, basis, table_seq, label_raw, adecimal
    FROM report_lines
    WHERE section_path = '주당손익' AND row_order IS NULL
      AND rcept_no = ANY(%s)
""", (list(rcepts),))
all_eps_rows = cur.fetchall()

extra_rows = []
for rcept_no, statement, basis, table_seq, label, adecimal in all_eps_rows:
    k = (rcept_no, statement, basis, table_seq)
    if k not in keys:
        continue
    known_labels = candidate_labels_by_key[k]
    if label in known_labels:
        continue  # this IS one of our candidate rows (possibly repeated across col_index)
    extra_rows.append((rcept_no, statement, basis, table_seq, label, adecimal))

print(f"\nrows in the SAME (rcept,statement,basis,table_seq) tables that are NOT part of the candidate label set: {len(extra_rows)}")

# classify these extras: do they have their own unit declaration (safe, untouched
# regardless of rcept-level override) or not (risk)?
risky_extras = []
for rcept_no, statement, basis, table_seq, label, adecimal in extra_rows:
    eps_cu = ColumnUnits.from_declaration(label)
    if eps_cu.kind == FX_ONLY:
        continue  # has own declaration (fx), safe
    if detect_unit_declaration(label) is not None:
        continue  # has own declaration, safe -- own_decl always wins over table fallback
    risky_extras.append((rcept_no, statement, basis, table_seq, label, adecimal))

print(f"of those, rows with NO own unit declaration (would be affected by an rcept-level override too): {len(risky_extras)}")
print("\n--- sample of risky_extras (if any) ---")
for r in risky_extras[:30]:
    print(f"  {r}")

conn.close()
