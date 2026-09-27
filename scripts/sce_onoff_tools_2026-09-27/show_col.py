import os, sys
sys.path.insert(0, os.getcwd())
from loguru import logger
logger.remove()
import psycopg2
from fin2.extract import report_lines as rl
rc, basis, ci = sys.argv[1], sys.argv[2], int(sys.argv[3])
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
cur.execute("select corp_code, fiscal_year, fiscal_period from filings where rcept_no=%s", (rc,))
corp, fy, fp = cur.fetchone()
cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' order by id desc", (rc,))
p = cur.fetchone()[0]; sd = "/Volumes/dart_data/raw_report/" + p.split("/raw_report/", 1)[1]
lines = rl.extract_report_lines(sd if os.path.exists(sd) else p, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True)
new = {(l.row_order, l.col_index): (l.value_won, l.label_raw, l.col_label) for l in lines if l.statement == "SCE" and l.basis == basis and l.value_won is not None}
cur.execute("select row_order, col_index, value_won from report_lines where rcept_no=%s and statement='SCE' and basis=%s", (rc, basis))
old = {(r[0], r[1]): r[2] for r in cur.fetchall()}
rows = sorted({k[0] for k in new} | {k[0] for k in old})
cols = sorted({k[1] for k in new})
print("cols:", {c: next(v[2] for k, v in new.items() if k[1] == c) for c in cols})
for ro in rows:
    lab = next((v[1] for k, v in new.items() if k[0] == ro), "")
    cells = []
    for c in cols:
        o = old.get((ro, c)); n = new.get((ro, c), (None,))[0]
        cells.append(f"{n}" if o == n else f"{o}->{n}")
    mark = "*" if any(old.get((ro, c)) != new.get((ro, c), (None,))[0] for c in cols) else " "
    print(mark, ro, lab[:22], " | ".join(cells) if ci < 0 else cells[cols.index(ci)] + "  || total:" + str(cells[-1]))
