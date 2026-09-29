"""Scan: completed xbrl_zip filings whose CURRENT extraction (loadable rows) differs from the DB.
Usage: python scan_xbrl_stale_vs_db.py <out.jsonl>   (needs DATABASE_URL, cwd = repo root)
Output per differing filing: cells only in the new extraction / only in the DB / changed values."""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())


def work(args):
    rc, path = args
    from loguru import logger
    logger.remove()
    import psycopg2
    import fin2.extract.report_lines_xbrl as X
    from fin2.extract.report_lines import _is_loadable
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period,period_end_date from filings where rcept_no=%s", (rc,))
    corp, fy, fp, pe = cur.fetchone()
    cur.execute("select statement,basis,table_seq,row_order,col_index,value_won,label_raw,unit_source from report_lines where rcept_no=%s", (rc,))
    db = {}
    manual = False
    for st, b, t, r, c, v, lab, us in cur.fetchall():
        db[(st, b, t, r, c)] = (v, lab)
        manual |= (us == "manual")
    cur.connection.close()
    lines = X.extract_report_lines_xbrl(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                        report_fiscal_period=fp, period_end_date=pe)
    new = {(l.statement, l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw)
           for l in lines if l.statement != "note" and _is_loadable(l)}
    only_new = [[list(k), v[1], v[0]] for k, v in new.items() if k not in db]
    only_db = [[list(k), v[1], v[0]] for k, v in db.items() if k not in new]
    changed = [[list(k), db[k][0], new[k][0], new[k][1]] for k in new if k in db and db[k][0] != new[k][0]]
    return rc, manual, only_new, only_db, changed


if __name__ == "__main__":
    import psycopg2
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select rcept_no,file_path from download_tasks where file_type='xbrl_zip' and status='completed' order by rcept_no")
    jobs = cur.fetchall()
    n = 0
    with Pool(8) as pool, open(sys.argv[1], "w") as fo:
        for i, (rc, manual, on_, od, ch) in enumerate(pool.imap_unordered(work, jobs, chunksize=4), 1):
            if on_ or od or ch:
                n += 1
                fo.write(json.dumps({"rcept": rc, "manual": manual, "only_new": on_, "only_db": od, "changed": ch}, ensure_ascii=False, default=str) + "\n"); fo.flush()
            if i % 400 == 0:
                print(i, "differing", n, flush=True)
    print("done", len(jobs), "differing", n)
