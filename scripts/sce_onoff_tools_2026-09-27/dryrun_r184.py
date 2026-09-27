"""Dry-run R184: re-extract scan-hit filings with current code, diff SCE vs DB."""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
import psycopg2
from loguru import logger
logger.remove(); logger.add(sys.stderr, level="WARNING")

SD, NAS_MARK = "/Volumes/dart_data/raw_report", "/raw_report/"

def work(rc):
    from fin2.extract import report_lines as rl
    conn = psycopg2.connect(os.environ["DATABASE_URL"]); cur = conn.cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,))
    corp, fy, fp = cur.fetchone()
    cur.execute("""select file_path from download_tasks where rcept_no=%s and status='completed'
                   and file_type='xml' and file_path is not null order by id desc""", (rc,))
    path = None
    for (p,) in cur.fetchall():
        cands = [p]
        if NAS_MARK in p:
            cands.insert(0, SD + "/" + p.split(NAS_MARK, 1)[1])
        for c in cands:
            if os.path.exists(c):
                path = c; break
        if path: break
    if not path:
        return rc, "nopath", []
    try:
        lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp)
    except Exception as e:
        return rc, f"err {e}", []
    new = {(l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw, l.col_label)
           for l in lines if l.statement == "SCE" and l.value_won is not None}
    cur.execute("""select basis,table_seq,row_order,col_index,value_won from report_lines
                   where rcept_no=%s and statement='SCE' and value_won is not null""", (rc,))
    old = {tuple(r[:4]): r[4] for r in cur.fetchall()}
    diffs = []
    for k in set(old) | set(new):
        o, n = old.get(k), new.get(k, (None,))[0]
        if o != n:
            diffs.append([list(k), o, n, (new.get(k) or (None, None, None))[1:]])
    return rc, "ok", diffs

if __name__ == "__main__":
    hits = [json.loads(l) for l in open(sys.argv[1])]
    rcepts = sorted({h["rcept"] for h in hits})
    with Pool(6) as pool, open(sys.argv[2], "w") as out:
        for i, (rc, st, diffs) in enumerate(pool.imap_unordered(work, rcepts), 1):
            out.write(json.dumps({"rcept": rc, "status": st, "diffs": diffs}, ensure_ascii=False, default=str) + "\n")
            if i % 50 == 0:
                print(i, flush=True)
    print("done", len(rcepts))
