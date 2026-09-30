"""Full on/off for R184-b (hierarchical total-only row fill): SCE cells that differ with the rule on and off, same worker, same DB state.
Usage: python measure_onoff_r184b.py <rcepts.jsonl> <out.jsonl>   (needs DATABASE_URL, cwd = repo root)"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")
from loguru import logger


def work(rc):
    logger.remove()
    import psycopg2
    import dryrun_full_on as D
    import fin2.extract.sce_sign_repair as ssr
    import fin2.extract.sce_source_defects as sd
    real = sd.fill_hierarchical_total_only_rows
    from fin2.extract import report_lines as rl
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,))
    corp, fy, fp = cur.fetchone()
    cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' and file_path is not null order by id desc", (rc,))
    path = None
    for (p,) in cur.fetchall():
        for c in ([D.SD + "/" + p.split(D.NAS_MARK, 1)[1]] if D.NAS_MARK in p else []) + [p]:
            if os.path.exists(c):
                path = c; break
        if path: break
    cur.connection.close()
    if not path:
        return rc, "nopath", [], []
    pb, pi = D._prior(rc, corp)
    out, events = {}, []
    ssr._RECORD_GUARD_EVENTS = True
    try:
        for mode in ("off", "on"):
            sd.fill_hierarchical_total_only_rows = real if mode == "on" else (lambda lines: 0)
            ssr.GUARD_EVENTS.clear()
            lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp,
                                            include_notes=True, prior_balances=pb, prior_income=pi)
            out[mode] = {(l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw, l.col_label)
                         for l in lines if l.statement == "SCE" and l.value_won is not None}
            if mode == "on":
                events = [[e[0]] for e in ssr.GUARD_EVENTS]
    except Exception as e:
        return rc, f"err {e}", [], []
    finally:
        sd.fill_hierarchical_total_only_rows = real
        ssr._RECORD_GUARD_EVENTS = False
    diffs = []
    for k in set(out["off"]) | set(out["on"]):
        a, b = out["off"].get(k, (None,))[0], out["on"].get(k, (None,))[0]
        if a != b:
            info = out["on"].get(k) or out["off"].get(k)
            diffs.append([list(k), a, b, info[1], info[2]])
    return rc, "ok", diffs, events


if __name__ == "__main__":
    rcepts = [json.loads(l)["rcept"] for l in open(sys.argv[1])]
    n_diff = n_ev = 0
    with Pool(8) as pool, open(sys.argv[2], "w") as out:
        for i, (rc, st, diffs, events) in enumerate(pool.imap_unordered(work, rcepts, chunksize=8), 1):
            if diffs or events or st not in ("ok", "nopath"):
                out.write(json.dumps({"rcept": rc, "status": st, "diffs": diffs, "events": events}, ensure_ascii=False, default=str) + "\n"); out.flush()
            n_diff += bool(diffs); n_ev += bool(events)
            if i % 2000 == 0:
                print(i, "diff filings", n_diff, "event filings", n_ev, flush=True)
    print("done", len(rcepts), "diff filings", n_diff, "event filings", n_ev)
