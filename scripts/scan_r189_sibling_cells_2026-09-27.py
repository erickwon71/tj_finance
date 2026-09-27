"""R189 candidates: run repair_sce_sibling_cells on the loaded SCE (+BS col 0) of every filing."""
import json, os, sys
import psycopg2
sys.path.insert(0, os.getcwd())
from loguru import logger
logger.remove()
from fin2.extract.sce_sign_repair import repair_sce_sibling_cells
out = open(sys.argv[1], "w")
class L:
    __slots__ = ("statement", "basis", "table_seq", "row_order", "col_index", "col_label", "label_raw", "value_won", "report_fiscal_period")
def handle(rc, rows):
    lines = []
    for st, b, s, ro, ci, cl, lab, v, fp in rows:
        l = L(); l.statement, l.basis, l.table_seq, l.row_order, l.col_index = st, b, s, ro, ci
        l.col_label, l.label_raw, l.value_won, l.report_fiscal_period = cl, lab, int(v), fp
        lines.append(l)
    fixes = repair_sce_sibling_cells(lines)
    for f in fixes:
        out.write(json.dumps({"rcept": rc, "basis": f.basis, "row": f.row_order, "col": f.col_label,
                              "label": f.label_raw, "old": f.old_value}, ensure_ascii=False) + "\n")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(name="r189"); cur.itersize = 200000
cur.execute("""select l.rcept_no, l.statement, l.basis, l.table_seq, l.row_order, l.col_index, l.col_label, l.label_raw, l.value_won, l.report_fiscal_period
               from report_lines l where l.value_won is not null and (l.statement='SCE' or (l.statement='BS' and l.col_index=0))
               order by l.rcept_no""")
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
