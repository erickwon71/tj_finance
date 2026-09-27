import os, sys
sys.path.insert(0, os.getcwd())
from loguru import logger
logger.remove()
import psycopg2
from collector.db import get_session
import fin2.extract.sce_sign_repair as sr
import fin2.extract.report_lines as rl
from fin2.extract.sce_dated_anchors import load_prior_balances, add_dated_anchors
rc, basis = sys.argv[1], sys.argv[2]
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
cur.execute("select corp_code, fiscal_year, fiscal_period from filings where rcept_no=%s", (rc,))
corp, fy, fp = cur.fetchone()
cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' order by id desc", (rc,))
p = cur.fetchone()[0]; sd = "/Volumes/dart_data/raw_report/" + p.split("/raw_report/", 1)[1]
with get_session() as s:
    prior = load_prior_balances(s, corp, rc)
def run(on):
    sr.add_dated_anchors = add_dated_anchors if on else (lambda a, l, p=None: a)
    corr = []
    orig = sr._apply
    def spy(cells, fixes, label, corrections):
        orig(cells, fixes, label, corrections)
    lines = rl.extract_report_lines(sd, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True, prior_balances=prior if on else None)
    return {(l.row_order, l.col_index): (l.value_won, l.label_raw, l.col_label) for l in lines if l.statement == "SCE" and l.basis == basis and l.value_won is not None}
off, on = run(False), run(True)
cols = sorted({k[1] for k in on})
print("cols", {c: next(v[2] for k, v in on.items() if k[1] == c).split(">")[-1] for c in cols})
for ro in sorted({k[0] for k in on}):
    lab = next(v[1] for k, v in on.items() if k[0] == ro)
    cells = []
    for c in cols:
        a = off.get((ro, c), (None,))[0]; b = on.get((ro, c), (None,))[0]
        cells.append(str(b) if a == b else f"{a}->{b}")
    print(("*" if any("->" in x for x in cells) else " "), ro, lab[:20], " | ".join(cells))
