"""R188 candidates in the DB: a positive SCE balance cell whose flip brings both its block
roll-forward and its row identity within 1,000 won (both > 1,000 before)."""
import json, os, re, sys
from collections import defaultdict
import psycopg2
sys.path.insert(0, os.getcwd())
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals, _row_identities
TOL = 1000
BAL = re.compile(r"기\s*초|기\s*말")
out = open(sys.argv[1], "w")
class L:
    __slots__ = ("value_won",)
    def __init__(s, v): s.value_won = v
def handle(rc, rows):
    cols = defaultdict(list); rws = defaultdict(dict)
    for b, s, ro, ci, cl, lab, v in rows:
        if ro is None:
            continue
        cols[(b, s, ci)].append((ro, lab or "", int(v)))
        if cl:
            rws[(b, s, ro)][tuple(x.strip() for x in cl.split(">"))] = (L(int(v)), ci)
    for (b, s, ci), ents in cols.items():
        ents.sort()
        cells = [_Cell(line=None, basis="", label_raw=l, col_label=None, value=v) for _, l, v in ents]
        for o, mv, c in _blocks(cells):
            sub = set(_proven_subtotals(cells, mv))
            res = cells[o].value + sum(cells[m].value for m in mv if m not in sub) - cells[c].value
            if abs(res) <= TOL:
                continue
            for idx, sgn in ((o, 1), (c, -1)):
                v = cells[idx].value
                if v <= TOL:
                    continue
                after = res - sgn * 2 * v
                if abs(after) > TOL:
                    continue
                ro = ents[idx][0]
                bp = {p: x[0] for p, x in rws[(b, s, ro)].items()}
                ids = _row_identities(bp)
                if not ids:
                    continue
                r0 = [abs(sum(bp[m].value_won for m in ms) - bp[t].value_won) for t, ms in ids]
                path = next((p for p, x in rws[(b, s, ro)].items() if x[1] == ci), None)
                if path is None or sum(r0) <= TOL:
                    continue
                bp[path].value_won = -v
                r1 = [abs(sum(bp[m].value_won for m in ms) - bp[t].value_won) for t, ms in ids]
                bp[path].value_won = v
                if all(x <= TOL for x in r1):
                    out.write(json.dumps({"rcept": rc, "basis": b, "seq": s, "row_order": ro,
                                          "col": ">".join(path), "label": ents[idx][1], "value": v,
                                          "rf_after": after, "row_after": sum(r1)},
                                         ensure_ascii=False) + "\n")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(name="r188_stream"); cur.itersize = 200000
cur.execute("""select rcept_no,basis,table_seq,row_order,col_index,col_label,label_raw,value_won
               from report_lines where statement='SCE' and value_won is not null order by rcept_no""")
cur_rc, buf, n = None, [], 0
for r in cur:
    if r[0] != cur_rc:
        if buf:
            handle(cur_rc, buf); n += 1
            if n % 20000 == 0: print(n, flush=True)
        cur_rc, buf = r[0], []
    buf.append(r[1:])
if buf: handle(cur_rc, buf)
print("done", n, flush=True)
