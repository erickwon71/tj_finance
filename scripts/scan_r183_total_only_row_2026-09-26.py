"""Scan: SCE movement rows printed only in a total column, where exactly one
component column's block roll-forward is off by exactly that amount."""
import json
import os
import re
import sys
from collections import defaultdict

import psycopg2

sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals

TOT = re.compile(r"합\s*계|총\s*계")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute(r"""
with r as (
 select rcept_no,basis,table_seq,row_order,count(*) n,
        bool_and(col_label ~ '합\s*계|총\s*계') all_tot, min(label_raw) lab
 from report_lines where statement='SCE' and value_won is not null and value_won<>0
 group by 1,2,3,4)
select distinct rcept_no from r where n=1 and all_tot and lab !~ '기초|기말|\d{4}[.]'""")
rcepts = [r[0] for r in cur.fetchall()]
hits = []
for rc in rcepts:
    cur.execute("""select basis,table_seq,row_order,col_index,col_label,label_raw,value_won
                   from report_lines where rcept_no=%s and statement='SCE' and value_won is not null""", (rc,))
    cols = defaultdict(list)   # (basis, seq, col) -> [(ro, label, v, col_label)]
    rows = defaultdict(dict)   # (basis, seq, ro) -> {col: (col_label, v)}
    for b, s, ro, ci, cl, lab, v in cur.fetchall():
        if ro is None:
            continue
        cols[(b, s, ci)].append((ro, lab or "", int(v), cl or ""))
        rows[(b, s, ro)][ci] = (cl or "", int(v), lab or "")
    for (b, s, ro), cells in rows.items():
        nz = {ci: c for ci, c in cells.items() if c[1] != 0}
        if len(nz) != 1:
            continue
        ci_t, (cl_t, v_t, lab) = next(iter(nz.items()))
        if not TOT.search(cl_t) or re.search(r"기초|기말|\d{4}[.]", lab):
            continue
        cands = []
        for (b2, s2, ci), ents in cols.items():
            if (b2, s2) != (b, s) or ci == ci_t or TOT.search(ents[0][3]):
                continue
            if any(e[0] == ro and e[2] != 0 for e in ents):
                continue
            ents = sorted(ents)
            cs = [_Cell(line=None, basis="", label_raw=e[1], col_label=None, value=e[2]) for e in ents]
            for o, mv, c in _blocks(cs):
                if not ents[o][0] < ro < ents[c][0]:
                    continue
                sub = set(_proven_subtotals(cs, mv))
                res = cs[o].value + sum(cs[m].value for m in mv if m not in sub) - cs[c].value
                if res == -v_t:
                    cands.append((ci, ents[0][3]))
        if len(cands) == 1:
            hits.append(dict(rcept=rc, basis=b, seq=s, row_order=ro, label=lab,
                             total_col=cl_t, value=v_t, fill_col=cands[0][1], fill_ci=cands[0][0]))
out = sys.argv[1]
with open(out, "w") as f:
    for h in hits:
        f.write(json.dumps(h, ensure_ascii=False) + "\n")
print("rcepts scanned", len(rcepts), "hits", len(hits), "filings", len({h['rcept'] for h in hits}))
