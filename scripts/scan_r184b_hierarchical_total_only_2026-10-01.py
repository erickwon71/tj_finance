"""Scan: hierarchical SCE movement rows whose only non-zero cells are a group subtotal
and the grand total (same value), while exactly one component column of that group has
a block roll-forward off by exactly -value (R184-b candidates; measurement only)."""
import json
import os
import re
import sys
from collections import defaultdict

import psycopg2

sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals

TOT = re.compile(r"합\s*계|총\s*계")
HEADING = re.compile(r"기초|기말|\d{4}[.]")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute(r"""
with r as (
 select rcept_no,basis,table_seq,row_order,count(*) n,
        bool_and(col_label ~ '합\s*계|총\s*계') all_tot, min(label_raw) lab
 from report_lines where statement='SCE' and value_won is not null and value_won<>0
 group by 1,2,3,4)
select distinct rcept_no from r where n=2 and all_tot""")
rcepts = [r[0] for r in cur.fetchall()]


def residual(ents, ro):
    ents = sorted(ents)
    cs = [_Cell(line=None, basis="", label_raw=e[1], col_label=None, value=e[2]) for e in ents]
    for o, mv, c in _blocks(cs):
        if not ents[o][0] < ro < ents[c][0]:
            continue
        sub = set(_proven_subtotals(cs, mv))
        return cs[o].value + sum(cs[m].value for m in mv if m not in sub) - cs[c].value
    return None


hits = []
for rc in rcepts:
    cur.execute("""select basis,table_seq,row_order,col_index,col_label,label_raw,value_won
                   from report_lines where rcept_no=%s and statement='SCE' and value_won is not null""", (rc,))
    cols = defaultdict(list)
    rows = defaultdict(dict)
    for b, s, ro, ci, cl, lab, v in cur.fetchall():
        if ro is None:
            continue
        cols[(b, s, ci)].append((ro, lab or "", int(v), cl or ""))
        rows[(b, s, ro)][ci] = (cl or "", int(v), lab or "")
    for (b, s, ro), cells in rows.items():
        nz = {ci: c for ci, c in cells.items() if c[1] != 0}
        if len(nz) != 2 or not all(TOT.search(c[0]) for c in nz.values()):
            continue
        (c1, (l1, v1, lab)), (c2, (l2, v2, _)) = list(nz.items())
        if v1 != v2 or HEADING.search(lab):
            continue
        # group total = the deeper path; grand total = the shallower one
        d1, d2 = l1.count(">"), l2.count(">")
        if d1 == d2:
            continue
        (cg, lg), (ct, lt) = ((c1, l1), (c2, l2)) if d1 > d2 else ((c2, l2), (c1, l1))
        prefix = lg.rsplit(">", 1)[0] + ">"
        cands = []
        for (b2, s2, ci), ents in cols.items():
            cl = ents[0][3]
            if (b2, s2) != (b, s) or TOT.search(cl) or not cl.startswith(prefix):
                continue
            if any(e[0] == ro for e in ents):
                continue
            if residual(ents, ro) == -v1:
                cands.append((ci, cl))
        if len(cands) != 1:
            continue
        if residual(cols[(b, s, cg)], ro) != 0 or residual(cols[(b, s, ct)], ro) != 0:
            continue
        hits.append(dict(rcept=rc, basis=b, seq=s, row_order=ro, label=lab, value=v1,
                         group_col=lg, fill_col=cands[0][1], fill_ci=cands[0][0]))
out = sys.argv[1]
with open(out, "w") as f:
    for h in hits:
        f.write(json.dumps(h, ensure_ascii=False) + "\n")
print("rcepts scanned", len(rcepts), "hits", len(hits), "filings", len({h['rcept'] for h in hits}))
