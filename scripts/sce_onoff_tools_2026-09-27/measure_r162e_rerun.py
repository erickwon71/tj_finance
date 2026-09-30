"""R162-e rerun after R162-d: what does a second `repair_sce_sign_loss` pass change?

One extraction per filing: `repair_sce_row_identity` is wrapped so that, when R162-d/d2 corrected any
cell, the sign-loss pass is run again and every cell it changes is recorded with the roll-forward
residual of its column block before/after and the IS sign of the same amount.
Usage: python measure_r162e_rerun.py <rcepts.jsonl|txt> <out.jsonl>   (needs DATABASE_URL, cwd = repo root)"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")


def _rcept(line):
    line = line.strip()
    return json.loads(line)["rcept"] if line.startswith("{") else line


def work(rc):
    from loguru import logger
    logger.remove()
    import psycopg2
    import dryrun_full_on as D
    import fin2.extract.sce_sign_repair as ssr
    from fin2.extract import report_lines as rl
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,))
    corp, fy, fp = cur.fetchone()
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
    events = []
    orig_d = rl.repair_sce_row_identity

    def wrapped(lines, *a, **k):
        fixes = orig_d(lines, *a, **k)
        if not fixes:
            return fixes
        before = {id(l): l.value_won for l in lines if l.statement == "SCE"}
        again = ssr.repair_sce_sign_loss(lines, pb, pi)
        is_signs = {}
        for l in lines:
            if l.statement == "IS" and l.value_won:
                is_signs.setdefault(abs(int(l.value_won)), set()).add(int(l.value_won) > 0)
        for l in lines:
            if l.statement == "SCE" and id(l) in before and before[id(l)] != l.value_won:
                after = l.value_won
                r_after = ssr._block_residual(lines, l)
                l.value_won = before[id(l)]
                r_before = ssr._block_residual(lines, l)
                l.value_won = after
                events.append({"key": [l.basis, l.table_seq, l.row_order, l.col_index], "label": l.label_raw,
                               "col": (l.col_label or "").split(">")[-1], "old": before[id(l)], "new": after,
                               "r_before": r_before, "r_after": r_after,
                               "is": sorted(is_signs.get(abs(int(after)), []))})
        return fixes

    rl.repair_sce_row_identity = wrapped
    try:
        rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp,
                                include_notes=True, prior_balances=pb, prior_income=pi)
    except Exception as e:
        return rc, f"err {e}", []
    finally:
        rl.repair_sce_row_identity = orig_d
    return rc, "ok", events


if __name__ == "__main__":
    rcepts = [_rcept(l) for l in open(sys.argv[1]) if l.strip()]
    n_ev = 0
    with Pool(8) as pool, open(sys.argv[2], "w") as out:
        for i, (rc, st, events) in enumerate(pool.imap_unordered(work, rcepts, chunksize=8), 1):
            if events or st not in ("ok", "nopath"):
                out.write(json.dumps({"rcept": rc, "status": st, "events": events}, ensure_ascii=False, default=str) + "\n")
                out.flush()
            n_ev += bool(events)
            if i % 1000 == 0:
                print(i, "filings with rerun changes", n_ev, flush=True)
    print("done", len(rcepts), "filings with rerun changes", n_ev)
