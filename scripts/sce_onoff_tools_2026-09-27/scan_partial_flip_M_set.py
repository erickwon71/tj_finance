"""Scope scan for R162-d partial column flips (도이치모터스 20110516003437 shape).

M (manifested): non-total SCE column with mixed-sign balance cells and a broken block.
   H_all: flipping every positive cell of the column closes every block.
   H_bal: flipping only positive balance cells closes every block.
L (latent): all balance cells positive, flat table (one total column), and at every
   balance row of the column the row identity fails as printed but closes with the
   column negated.
"""
import json, os, re, sys
from collections import defaultdict
import psycopg2
sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals

TOT = re.compile(r"합\s*계|총\s*계")
out = open(sys.argv[1], "w")

def residuals(ents):
    cells = [_Cell(line=None, basis="", label_raw=e[1], col_label=None, value=e[2]) for e in ents]
    res = []
    for o, mv, c in _blocks(cells):
        sub = set(_proven_subtotals(cells, mv))
        res.append((o, c, cells[o].value + sum(cells[m].value for m in mv if m not in sub) - cells[c].value))
    return res

def handle(rc, rows):
    tables = defaultdict(list)
    for b, s, ro, ci, cl, lab, v in rows:
        if ro is not None:
            tables[(b, s)].append((ro, ci, cl or "", lab or "", int(v)))
    for (b, s), cells in tables.items():
        cols = defaultdict(list); labels = {}
        for ro, ci, cl, lab, v in cells:
            cols[ci].append((ro, lab, v)); labels[ci] = cl
        tot = [ci for ci, cl in labels.items() if TOT.search(cl)]
        byrow = defaultdict(dict)
        for ro, ci, cl, lab, v in cells:
            byrow[ro][ci] = v
        for ci, ents in cols.items():
            if ci in tot:
                continue
            ents.sort()
            blocks = residuals(ents)
            if not blocks:
                continue
            bal_idx = {i for o, c, _ in blocks for i in (o, c)}
            bal_vals = [ents[i][2] for i in bal_idx]
            broken = any(r != 0 for _, _, r in blocks)
            has_pos = any(v > 0 for v in bal_vals); has_neg = any(v < 0 for v in bal_vals)
            if has_pos and has_neg and broken:
                flip_all = [(ro, lab, -v if v > 0 else v) for ro, lab, v in ents]
                flip_bal = [(ro, lab, -v if (i in bal_idx and v > 0) else v) for i, (ro, lab, v) in enumerate(ents)]
                h_all = all(r == 0 for _, _, r in residuals(flip_all))
                h_bal = all(r == 0 for _, _, r in residuals(flip_bal))
                out.write(json.dumps({"k": "M", "rcept": rc, "basis": b, "seq": s, "col": labels[ci],
                                      "h_all": h_all, "h_bal": h_bal}, ensure_ascii=False) + "\n")
            elif has_pos and not has_neg and len(tot) == 1 and not broken:
                t = tot[0]; ok = True
                for i in bal_idx:
                    ro = ents[i][0]; row = byrow[ro]
                    if t not in row:
                        ok = False; break
                    parts = sum(v for c2, v in row.items() if c2 != t)
                    if parts == row[t] or parts - 2 * row[ci] != row[t]:
                        ok = False; break
                if ok:
                    out.write(json.dumps({"k": "L", "rcept": rc, "basis": b, "seq": s, "col": labels[ci]},
                                         ensure_ascii=False) + "\n")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(name="sce_stream")
cur.itersize = 200000
cur.execute("""select rcept_no,basis,table_seq,row_order,col_index,col_label,label_raw,value_won
               from report_lines where statement='SCE' and value_won is not null order by rcept_no""")
cur_rc, buf, n = None, [], 0
for r in cur:
    if r[0] != cur_rc:
        if buf:
            handle(cur_rc, buf); n += 1
            if n % 20000 == 0:
                print(n, flush=True)
        cur_rc, buf = r[0], []
    buf.append(r[1:])
if buf:
    handle(cur_rc, buf); n += 1
print("done", n, flush=True)
