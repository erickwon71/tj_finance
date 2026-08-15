"""
Precise re-confirmation of the curated rcept_no allowlist for
_emit_eps_lines K-GAAP legacy label unit-fallback fix
(docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md §4-B).

Strategy (stronger than pure label-text heuristics, per feedback-verify-against-source):
cross-validate each risk-group candidate's table-scaled value against an
INDEPENDENT total already present in std_financials_v3 (net_income / controlling_ni
for the same corp+fy+period, either basis) wherever available. A match within
tolerance is a near-airtight confirmation that "raw_value * table_unit" is the
true net-income headline figure -- i.e. this row IS the K-GAAP bug pattern, not
a genuine EPS value (a genuine EPS value scaled by table_unit would almost never
coincidentally match a company's total net income).

Rows without any independent total to cross-check fall back to the text-signal
tier (lower confidence, flagged separately -- NOT auto-included in the curated set).
"""
import sys, os, re, json
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import psycopg2
from parser.common.amount_normalizer import detect_unit_declaration
from fin2.extract.units import ColumnUnits, FX_ONLY
from collections import defaultdict

conn = psycopg2.connect(dbname="tj_finance")
cur = conn.cursor()

print("Step 1: build risk candidate rows (label no own decl + sibling table real unit in {천원,백만원})")
cur.execute("""
    SELECT rcept_no, statement, basis, table_seq, label_raw, corp_code,
           report_fiscal_year, report_fiscal_period, value_won
    FROM report_lines
    WHERE section_path = '주당손익' AND row_order IS NULL AND adecimal = 0
""")
rows = cur.fetchall()

no_decl = []
for (rcept_no, statement, basis, table_seq, label, corp_code, fy, period, value_won) in rows:
    eps_cu = ColumnUnits.from_declaration(label)
    if eps_cu.kind == FX_ONLY:
        continue
    if detect_unit_declaration(label) is None:
        no_decl.append((rcept_no, statement, basis, table_seq, label, corp_code, fy, period, value_won))

key_set = set((r[0], r[1], r[2], r[3]) for r in no_decl)
cur.execute("""
    SELECT rcept_no, statement, basis, table_seq, adecimal, count(*)
    FROM report_lines
    WHERE row_order IS NOT NULL
    GROUP BY rcept_no, statement, basis, table_seq, adecimal
""")
counts = defaultdict(lambda: defaultdict(int))
for rcept_no, statement, basis, table_seq, adecimal, c in cur.fetchall():
    key = (rcept_no, statement, basis, table_seq)
    if key in key_set:
        counts[key][adecimal] += c

def mode_adecimal(key):
    d = counts.get(key)
    if not d:
        return None
    return max(d.items(), key=lambda kv: kv[1])[0]

risk = []
for item in no_decl:
    key = item[:4]
    m = mode_adecimal(key)
    if m in (-3, -6):
        risk.append(item + (m,))

print(f"  risk candidates: {len(risk)} rows")

print("\nStep 2: cross-validate against std_financials_v3 net_income/controlling_ni")
# Preload std_v3 totals for all (corp, fy, period, basis) touched, batched.
needed_keys = set((r[5], r[6], r[7], r[2]) for r in risk)  # corp, fy, period, basis
corps = tuple(sorted(set(k[0] for k in needed_keys)))
cur.execute("""
    SELECT corp_code, fiscal_year, fiscal_period, statement_type, net_income, controlling_ni
    FROM std_financials_v3
    WHERE corp_code = ANY(%s)
""", (list(corps),))
std_lookup = {}
for corp_code, fy, period, stype, ni, cni in cur.fetchall():
    std_lookup[(corp_code, fy, period, stype)] = (ni, cni)

MULT = {-3: 1000, -6: 1_000_000}
NUM_WON_RE = re.compile(r'[0-9][0-9,\.]*\s*원')
HEADLINE_RE = re.compile(r'당기순이익|처분전|반기순이익|분기순이익|당기순손실|순손실|순이익')

confirmed = []       # cross-validated against independent std_v3 total
likely_no_xref = []  # text signals present but no std_v3 total to cross-check
rejected = []        # neither cross-validated nor strong text signal

for item in risk:
    (rcept_no, statement, basis, table_seq, label, corp_code, fy, period, value_won, table_adec) = item
    mult = MULT[table_adec]
    scaled = value_won * mult if value_won is not None else None

    std_key = (corp_code, fy, period, basis)
    ni, cni = std_lookup.get(std_key, (None, None))

    xref_match = False
    xref_detail = None
    for label_name, total in (("net_income", ni), ("controlling_ni", cni)):
        if total is None or scaled is None or total == 0:
            continue
        rel_diff = abs(scaled - total) / abs(total)
        if rel_diff < 0.01:  # within 1%
            xref_match = True
            xref_detail = (label_name, total, rel_diff)
            break

    has_headline = bool(HEADLINE_RE.search(label))
    has_num = bool(NUM_WON_RE.search(label))

    record = dict(rcept_no=rcept_no, statement=statement, basis=basis, table_seq=table_seq,
                  label=label, corp_code=corp_code, fy=fy, period=period,
                  value_won=value_won, table_adec=table_adec, scaled=scaled,
                  xref_match=xref_match, xref_detail=xref_detail,
                  has_headline=has_headline, has_num=has_num)

    if xref_match:
        confirmed.append(record)
    elif has_headline and has_num:
        likely_no_xref.append(record)
    else:
        rejected.append(record)

print(f"  CONFIRMED (cross-validated vs std_v3 total, <1% diff): {len(confirmed)} rows")
print(f"  LIKELY (headline+embedded-number text signal, no std_v3 total to check): {len(likely_no_xref)} rows")
print(f"  REJECTED (neither): {len(rejected)} rows")

def summarize(name, records):
    filings = set((r['corp_code'], r['fy'], r['period']) for r in records)
    rcepts = set(r['rcept_no'] for r in records)
    corps = set(r['corp_code'] for r in records)
    print(f"  [{name}] rows={len(records)} distinct_filings(corp+fy+period)={len(filings)} distinct_rcept={len(rcepts)} distinct_corp={len(corps)}")

print()
summarize("CONFIRMED", confirmed)
summarize("LIKELY", likely_no_xref)
summarize("REJECTED", rejected)

print("\n--- sample CONFIRMED rows (cross-validated) ---")
for r in confirmed[:10]:
    print(f"  corp={r['corp_code']} fy={r['fy']} period={r['period']} basis={r['basis']} "
          f"label={r['label'][:60]!r} raw={r['value_won']} scaled={r['scaled']} xref={r['xref_detail']}")

print("\n--- sample LIKELY rows (text signal only, no xref) ---")
for r in likely_no_xref[:10]:
    print(f"  corp={r['corp_code']} fy={r['fy']} period={r['period']} basis={r['basis']} "
          f"label={r['label'][:60]!r} raw={r['value_won']} scaled={r['scaled']}")

print("\n--- sample REJECTED rows that DID have headline word (check for missed embedded-number variants) ---")
rej_headline_only = [r for r in rejected if r['has_headline'] and not r['has_num']][:15]
for r in rej_headline_only:
    print(f"  corp={r['corp_code']} fy={r['fy']} period={r['period']} label={r['label'][:80]!r}")

# Persist full result for further inspection
out = {
    "confirmed": confirmed,
    "likely_no_xref": likely_no_xref,
}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "eps_curated_candidates_2026-08-15.json"), "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)

conn.close()
print("\nDONE, saved candidates JSON.")
