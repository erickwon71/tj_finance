import os, sys
sys.path.insert(0, os.getcwd()); sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")
from loguru import logger
from dryrun_full_on import _prior, SD, NAS_MARK
import fin2.extract.sce_sign_repair as ssr
from fin2.extract import report_lines as rl
logger.remove()
import psycopg2
rc, basis, col = sys.argv[1], sys.argv[2], int(sys.argv[3])
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,)); corp, fy, fp = cur.fetchone()
cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' order by id desc", (rc,))
path = SD + "/" + cur.fetchone()[0].split(NAS_MARK, 1)[1]
pb, pi = _prior(rc, corp)
orig_anchor = ssr.add_prior_income_anchors
def anc(a, lines, p=None):
    out = orig_anchor(a, lines, p)
    for ln in lines:
        s = out.get(("prior_is", id(ln)))
        if s and ln.basis == basis and ln.col_index == col:
            per = ssr.block_period(lines, ln)
            print("  ANCHOR", ln.row_order, ln.label_raw[:20], ln.value_won, "->", s, per, [x for x in pi.get(per, ()) if abs(x[2]) == abs(ln.value_won)][:3])
    return out
ssr.add_prior_income_anchors = anc
orig = ssr._apply
def spy(cells, fixes, label, corrections):
    for i, s in fixes:
        if cells[i].line.basis == basis and cells[i].line.col_index == col:
            print("  FIX", cells[i].line.row_order, cells[i].label_raw[:16], cells[i].value, "->", s, "|", label)
    return orig(cells, fixes, label, corrections)
ssr.add_prior_income_anchors = anc
lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True, prior_balances=pb, prior_income=pi)
for l in sorted((l for l in lines if l.statement == "SCE" and l.basis == basis and l.col_index == col), key=lambda l: l.row_order):
    print("   ", l.row_order, l.label_raw[:22], l.value_won)
