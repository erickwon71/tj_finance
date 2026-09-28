import os, sys
sys.path.insert(0, os.getcwd())
from loguru import logger; logger.remove()
import psycopg2
sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")
from dryrun_full_on import _prior, SD, NAS_MARK
from fin2.extract import report_lines as rl
rc, basis, r0, r1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,)); corp, fy, fp = cur.fetchone()
cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' order by id desc", (rc,))
path = SD + "/" + cur.fetchone()[0].split(NAS_MARK, 1)[1]
lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True, **dict(zip(('prior_balances','prior_income'), _prior(rc, corp))))
for l in sorted((l for l in lines if l.statement == "SCE" and l.basis == basis and r0 <= (l.row_order or 0) <= r1), key=lambda l: (l.table_seq, l.row_order, l.col_index or 0)):
    print(l.table_seq, l.row_order, l.col_index, l.label_raw[:20], l.value_won, repr(l.value_raw), l.header_hint)
