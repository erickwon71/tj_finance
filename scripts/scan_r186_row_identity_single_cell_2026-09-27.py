"""Candidates for R186: SCE rows whose identities fail in the DB but all hold if exactly
one negative cell is made positive (the trace an R162-e mis-flip leaves)."""
import json, os, sys
from collections import defaultdict
import psycopg2
sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _row_identities

out = open(sys.argv[1], "w")

class _L:
    __slots__ = ("value_won",)
    def __init__(self, v): self.value_won = v

def holds(by_path, idents):
    return all(sum(by_path[m].value_won for m in ms) == by_path[t].value_won for t, ms in idents)

def handle(rc, rows):
    grp = defaultdict(dict)
    for b, s, ro, cl, lab, v in rows:
        if ro is None or not cl:
            continue
        grp[(b, s, ro)][tuple(x.strip() for x in cl.split(">"))] = (_L(int(v)), lab)
    for (b, s, ro), cells in grp.items():
        by_path = {p: c[0] for p, c in cells.items()}
        idents = _row_identities(by_path)
        if not idents or holds(by_path, idents):
            continue
        sols = []
        for p, ln in by_path.items():
            if ln.value_won >= 0:
                continue
            ln.value_won = -ln.value_won
            if holds(by_path, idents):
                sols.append(p)
            ln.value_won = -ln.value_won
        if len(sols) == 1:
            p = sols[0]
            out.write(json.dumps({"rcept": rc, "basis": b, "seq": s, "row_order": ro,
                                  "col": ">".join(p), "label": next(iter(cells.values()))[1],
                                  "value": by_path[p].value_won}, ensure_ascii=False) + "\n")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(name="r186_stream")
cur.itersize = 200000
cur.execute("""select rcept_no,basis,table_seq,row_order,col_label,label_raw,value_won
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
