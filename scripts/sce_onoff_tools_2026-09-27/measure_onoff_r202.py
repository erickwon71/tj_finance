"""On/off for R202 (leading digits split off inside one cell, parse_amount): every extracted cell that differs.
Usage: python measure_onoff_r202.py <rcepts.txt> <out.jsonl>   (needs DATABASE_URL, cwd = repo root)"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")


def work(rc):
    from loguru import logger
    logger.remove()
    import psycopg2
    import dryrun_full_on as D
    import parser.common.amount_normalizer as AN
    from fin2.extract import report_lines as rl
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,))
    row = cur.fetchone()
    if not row:
        return rc, "nofiling", []
    corp, fy, fp = row
    cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' "
                "and file_path is not null order by id desc", (rc,))
    path = None
    for (p,) in cur.fetchall():
        for c in ([D.SD + "/" + p.split(D.NAS_MARK, 1)[1]] if D.NAS_MARK in p else []) + [p]:
            if os.path.exists(c):
                path = c
                break
        if path:
            break
    cur.connection.close()
    if not path:
        return rc, "nopath", []
    pb, pi = D._prior(rc, corp)
    out = {}
    try:
        for mode in ("off", "on"):
            AN._R202_SPLIT_LEADING_DIGITS = (mode == "on")
            lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                            report_fiscal_period=fp, include_notes=True,
                                            prior_balances=pb, prior_income=pi)
            out[mode] = {(l.statement, l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw)
                         for l in lines}
    except Exception as e:
        return rc, f"err {e}", []
    finally:
        AN._R202_SPLIT_LEADING_DIGITS = True
    diffs = []
    for k in set(out["off"]) | set(out["on"]):
        a, b = out["off"].get(k, (None,))[0], out["on"].get(k, (None,))[0]
        if a != b:
            diffs.append([list(k), a, b, (out["on"].get(k) or out["off"].get(k))[1]])
    return rc, "ok", diffs


if __name__ == "__main__":
    rcepts = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    n = 0
    with Pool(8) as pool, open(sys.argv[2], "w") as fo:
        for i, (rc, st, diffs) in enumerate(pool.imap_unordered(work, rcepts, chunksize=4), 1):
            if diffs or st not in ("ok",):
                fo.write(json.dumps({"rcept": rc, "status": st, "diffs": diffs}, ensure_ascii=False, default=str) + "\n")
                fo.flush()
            n += bool(diffs)
            if i % 200 == 0:
                print(i, "diff filings", n, flush=True)
    print("done", len(rcepts), "diff filings", n)
