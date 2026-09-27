"""Recheck set: opening cells without usable prior-report evidence whose own table is broken."""
import json, os, sys, collections
import psycopg2
sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals, _row_identities
S = sys.argv[1]
cells = collections.defaultdict(list)
for l in open(f"{S}/prior_opening.jsonl"):
    d = json.loads(l)
    if d["k"] in ("noprior", "no magnitude match in prior", "prior has both signs"):
        cells[d["cell"][0]].append((d["k"], d["cell"]))
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
class L:
    def __init__(s, v): s.value_won = v
stat = collections.Counter(); out = open(f"{S}/recheck_cells.jsonl", "w"); fil = collections.defaultdict(set)
for i, (rc, cs) in enumerate(cells.items()):
    cur.execute("""select basis, table_seq, row_order, col_index, col_label, label_raw, value_won
                   from report_lines where rcept_no=%s and statement='SCE' and value_won is not null""", (rc,))
    allr = [r for r in cur.fetchall() if r[2] is not None]
    cols = collections.defaultdict(list); rows = collections.defaultdict(dict)
    for b, s, ro, ci, cl, lab, v in allr:
        cols[(b, s, ci)].append((ro, lab or "", int(v)))
        if cl:
            rows[(b, s, ro)][tuple(x.strip() for x in cl.split(">"))] = L(int(v))
    for k, (rc_, b, s, ro, ci, cl, lab, v, prev) in cs:
        ents = sorted(cols[(b, s, ci)])
        cc = [_Cell(line=None, basis="", label_raw=l, col_label=None, value=x) for _, l, x in ents]
        rf = None
        for o, mv, c in _blocks(cc):
            if ents[o][0] <= ro <= ents[c][0]:
                sub = set(_proven_subtotals(cc, mv))
                rf = cc[o].value + sum(cc[m].value for m in mv if m not in sub) - cc[c].value
                break
        bp = rows[(b, s, ro)]
        ids = _row_identities(bp)
        row_ok = all(sum(bp[m].value_won for m in ms) == bp[t].value_won for t, ms in ids)
        broken = (rf not in (0, None)) or (ids and not row_ok)
        stat[(k, "BROKEN" if broken else "ok")] += 1
        if broken:
            fil[k].add(rc)
            out.write(json.dumps({"k": k, "cell": [rc, b, s, ro, ci, cl, lab, v, prev], "rf": rf,
                                  "row_ok": row_ok if ids else None}, ensure_ascii=False, default=str) + "\n")
    if i % 5000 == 0:
        print(i, len(cells), flush=True)
for k, n in sorted(stat.items()):
    print(k, n)
for k, f in fil.items():
    print("filings", k, len(f))
print("done", flush=True)
