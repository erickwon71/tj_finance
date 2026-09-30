"""R176 tie policy: legacy (set order, PYTHONHASHSEED-dependent) vs first vs strict, same worker, all xbrl_zip filings.
Usage: PYTHONHASHSEED=<n> python measure_onoff_r200.py <out.jsonl>   (needs DATABASE_URL, cwd = repo root)"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
POLICIES = ("legacy", "first", "strict")


def work(args):
    rc, path = args
    from loguru import logger
    logger.remove()
    import psycopg2
    import fin2.extract.report_lines_xbrl as X
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period,period_end_date from filings where rcept_no=%s", (rc,))
    corp, fy, fp, pe = cur.fetchone()
    cur.connection.close()
    out = {}
    try:
        for pol in POLICIES:
            X._R176_TIE_POLICY = pol
            lines = X.extract_report_lines_xbrl(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                                report_fiscal_period=fp, period_end_date=pe)
            out[pol] = {(l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw)
                        for l in lines if l.statement == "SCE" and l.value_won is not None}
    except Exception as e:
        return rc, f"err {e}", {}
    finally:
        X._R176_TIE_POLICY = "strict"
    diffs = {}
    for pol in ("first", "strict"):
        d = [[list(k), out["legacy"].get(k, (None,))[0], v[0], v[1]] for k, v in out[pol].items()
             if out["legacy"].get(k, (None,))[0] != v[0]]
        if d:
            diffs[pol] = d
    fs = [[list(k), out["first"].get(k, (None,))[0], v[0], v[1]] for k, v in out["strict"].items()
          if out["first"].get(k, (None,))[0] != v[0]]
    if fs:
        diffs["first_vs_strict"] = fs
    return rc, "ok", diffs


if __name__ == "__main__":
    import psycopg2
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select rcept_no,file_path from download_tasks where file_type='xbrl_zip' and status='completed' order by rcept_no")
    jobs = cur.fetchall()
    n = 0
    with Pool(8) as pool, open(sys.argv[1], "w") as fo:
        for i, (rc, st, diffs) in enumerate(pool.imap_unordered(work, jobs, chunksize=4), 1):
            if diffs or st != "ok":
                n += 1
                fo.write(json.dumps({"rcept": rc, "status": st, "diffs": diffs}, ensure_ascii=False, default=str) + "\n"); fo.flush()
            if i % 400 == 0:
                print(i, "differing", n, flush=True)
    print("done", len(jobs), "differing", n)
