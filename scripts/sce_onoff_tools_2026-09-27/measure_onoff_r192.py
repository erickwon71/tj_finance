"""Full 2015+ on/off: SCE cells that differ between R192 on (current tree) and off (HEAD behaviour)."""
import json, os, re, sys
from multiprocessing import Pool
sys.path.insert(0, os.getcwd())
sys.path.insert(0, "scripts/sce_onoff_tools_2026-09-27")
from loguru import logger
OLD_RE = re.compile(r"^[\s\dⅠ-Ⅹ().]*(세후\s*)?(기타\s*)?포괄\s*(손익|이익|손실)|재분류|지배기업|소유주")

def work(rc):
    logger.remove()
    import psycopg2
    import dryrun_full_on as D
    import fin2.extract.sce_sign_repair as ssr
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
    if not path:
        return rc, "nopath", []
    pb, pi = D._prior(rc, corp)
    import importlib.util
    from collector.db import get_session
    spec = importlib.util.spec_from_file_location("old_sda", os.path.join(os.path.dirname(os.path.abspath(__file__)), "old_sda.py"  # git show <base>:fin2/extract/sce_dated_anchors.py > old_sda.py next to this script))
    old_sda = importlib.util.module_from_spec(spec); spec.loader.exec_module(old_sda)
    with get_session() as ss:
        pi_old = old_sda.load_prior_income(ss, corp, rc)
    new_re, new_anchor = ssr._INCOME_SUBTOTAL_RE, ssr.add_prior_income_anchors
    out = {}
    try:
        for mode in ("off", "on"):
            if mode == "off":
                ssr._INCOME_SUBTOTAL_RE, ssr.add_prior_income_anchors = OLD_RE, (lambda a, l, p=None: a)
            else:
                ssr._INCOME_SUBTOTAL_RE, ssr.add_prior_income_anchors = new_re, new_anchor
            lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp,
                                            include_notes=True, prior_balances=pb, prior_income=(pi_old if mode == "off" else pi))
            out[mode] = {(l.basis, l.table_seq, l.row_order, l.col_index): (l.value_won, l.label_raw, l.col_label)
                         for l in lines if l.statement == "SCE" and l.value_won is not None}
    except Exception as e:
        return rc, f"err {e}", []
    finally:
        ssr._INCOME_SUBTOTAL_RE, ssr.add_prior_income_anchors = new_re, new_anchor
    diffs = []
    for k in set(out["off"]) | set(out["on"]):
        a, b = out["off"].get(k, (None,))[0], out["on"].get(k, (None,))[0]
        if a != b:
            info = out["on"].get(k) or out["off"].get(k)
            diffs.append([list(k), a, b, info[1], info[2]])
    return rc, "ok", diffs

if __name__ == "__main__":
    rcepts = [json.loads(l)["rcept"] for l in open(sys.argv[1])]
    with Pool(8) as pool, open(sys.argv[2], "w") as out:
        for i, (rc, st, diffs) in enumerate(pool.imap_unordered(work, rcepts, chunksize=8), 1):
            if diffs or st not in ("ok", "nopath"):
                out.write(json.dumps({"rcept": rc, "status": st, "diffs": diffs}, ensure_ascii=False, default=str) + "\n"); out.flush()
            if i % 5000 == 0:
                print(i, flush=True)
    print("done", len(rcepts))
