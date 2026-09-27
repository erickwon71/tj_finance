import json, os, sys, collections
sys.path.insert(0, os.getcwd())
from loguru import logger
logger.remove()
from multiprocessing import Pool
S = sys.argv[1]
eff = json.load(open(f"{S}/r189_effect.json"))
by = collections.defaultdict(list)
for k, t in eff:
    by[k[0]].append((tuple(k[1:]), t))
def work(item):
    rc, cells = item
    import psycopg2
    from collector.db import get_session
    from fin2.extract import report_lines as rl
    from fin2.extract.sce_dated_anchors import load_prior_balances, add_dated_anchors
    from fin2.extract.sce_sign_repair import (_block_residual, _required_sign, _Cell,
                                              build_sign_anchors, _is_balance_label)
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code, fiscal_year, fiscal_period from filings where rcept_no=%s", (rc,))
    corp, fy, fp = cur.fetchone()
    cur.execute("select file_path from download_tasks where rcept_no=%s and status='completed' and file_type='xml' order by id desc", (rc,))
    p = cur.fetchone()[0]; sd = "/Volumes/dart_data/raw_report/" + p.split("/raw_report/", 1)[1]
    with get_session() as s:
        prior = load_prior_balances(s, corp, rc)
    lines = rl.extract_report_lines(sd if os.path.exists(sd) else p, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True, prior_balances=prior)
    anchors = add_dated_anchors(build_sign_anchors(lines), lines, prior)
    ext = collections.defaultdict(set)
    for l in lines:
        if l.statement in ("IS", "CF") and l.col_index == 0 and l.value_won:
            ext[abs(int(l.value_won))].add(int(l.value_won) > 0)
    idx = {(l.basis, l.table_seq, l.row_order, l.col_index): l for l in lines if l.statement == "SCE" and l.value_won is not None}
    out = []
    for key, (offv, onv, meta) in cells:
        l = idx.get(key)
        if l is None or offv is None or onv is None:
            out.append(("n/a", "n/a", "n/a")); continue
        r_on = _block_residual(lines, l); l.value_won = offv; r_off = _block_residual(lines, l); l.value_won = onv
        exact = "rf closes exactly" if r_on == 0 else ("rf shrinks" if (r_on is not None and r_off is not None and abs(r_on) < abs(r_off)) else "rf other")
        bal = _is_balance_label(l.label_raw or "")
        if bal:
            sign, lab = _required_sign(_Cell(line=l, basis=l.basis, label_raw=l.label_raw, col_label=l.col_label, value=onv), anchors)
            ev = "BS agrees" if sign == (1 if onv > 0 else -1) else ("BS DISAGREES" if sign else "no BS evidence")
        else:
            s_ = ext.get(abs(onv))
            ev = "no IS/CF evidence" if not s_ else ("IS/CF both signs" if len(s_) == 2 else ("IS/CF agrees" if (onv > 0) in s_ else "IS/CF DISAGREES"))
        out.append(("balance" if bal else "movement", exact, ev))
    return out
if __name__ == "__main__":
    c = collections.Counter()
    with Pool(6) as pool:
        for res in pool.imap_unordered(work, list(by.items())):
            for r in res: c[r] += 1
    for k, n in sorted(c.items(), key=lambda x: -x[1]): print(n, k)
