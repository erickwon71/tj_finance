"""On/off for R199 (2nd IS role of an XBRL filing): rows added/changed per filing, same worker.
Usage: python measure_onoff_r199.py <out.jsonl>   (all completed xbrl_zip filings; needs DATABASE_URL, cwd = repo root)"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())


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
        for mode in ("off", "on"):
            X._EMIT_EXTRA_IS_ROLES = (mode == "on")
            lines = X.extract_report_lines_xbrl(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                                report_fiscal_period=fp, period_end_date=pe)
            out[mode] = {(l.statement, l.basis, l.table_seq, l.row_order, l.col_index): (l.label_raw, l.value_won) for l in lines}
    except Exception as e:
        return rc, f"err {e}", [], []
    finally:
        X._EMIT_EXTRA_IS_ROLES = True
    added = [[list(k), v[0], v[1]] for k, v in out["on"].items() if k not in out["off"]]
    changed = [[list(k), out["off"][k], out["on"][k]] for k in out["off"] if out["on"].get(k) != out["off"][k]]
    return rc, "ok", added, changed


if __name__ == "__main__":
    import psycopg2
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select rcept_no,file_path from download_tasks where file_type='xbrl_zip' and status='completed' order by rcept_no")
    jobs = cur.fetchall()
    n_add = n_chg = 0
    with Pool(8) as pool, open(sys.argv[1], "w") as fo:
        for i, (rc, st, added, changed) in enumerate(pool.imap_unordered(work, jobs, chunksize=4), 1):
            if added or changed or st != "ok":
                fo.write(json.dumps({"rcept": rc, "status": st, "added": added, "changed": changed}, ensure_ascii=False, default=str) + "\n"); fo.flush()
            n_add += bool(added); n_chg += bool(changed)
            if i % 400 == 0:
                print(i, "added-filings", n_add, "changed-filings", n_chg, flush=True)
    print("done", len(jobs), "added-filings", n_add, "changed-filings", n_chg)
