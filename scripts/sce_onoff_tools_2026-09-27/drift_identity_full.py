import json, os, sys, collections
sys.path.insert(0, os.getcwd())
from loguru import logger
logger.remove()
from multiprocessing import Pool
S = sys.argv[1]
sys.path.insert(0, S)
import dryrun_r184 as D

def _pb(rc, corp):
    from collector.db import get_session
    from fin2.extract.sce_dated_anchors import load_prior_evidence
    with get_session() as ss:
        return load_prior_evidence(ss, corp, rc)


def check(item):
    rc, diffs = item
    from fin2.extract import report_lines as rl
    from fin2.extract.sce_source_defects import _column_entries, _residual_at
    from fin2.extract.sce_sign_repair import _row_identities_hold
    import psycopg2
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("select corp_code,fiscal_year,fiscal_period from filings where rcept_no=%s", (rc,))
    corp, fy, fp = cur.fetchone()
    cur.execute("""select file_path from download_tasks where rcept_no=%s and status='completed'
                   and file_type='xml' and file_path is not null order by id desc""", (rc,))
    path = None
    for (p,) in cur.fetchall():
        for c in ([D.SD + "/" + p.split(D.NAS_MARK, 1)[1]] if D.NAS_MARK in p else []) + [p]:
            if os.path.exists(c):
                path = c; break
        if path: break
    lines = rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy, report_fiscal_period=fp, include_notes=True, **dict(zip(('prior_balances','prior_income'), _pb(rc, corp))))
    sce = {(l.basis, l.table_seq, l.row_order, l.col_index): l for l in lines if l.statement == "SCE" and l.value_won is not None}
    old_override = {}
    for k, o, n, _ in diffs:
        l = sce.get(tuple(k))
        if l is not None and o is not None:
            old_override[id(l)] = (l.row_order, o)
    out = collections.Counter()
    for k, o, n, _ in diffs:
        if o is None or n is None:
            out["add/remove"] += 1; continue
        b, seq, ro, ci = k
        rn = _residual_at(_column_entries(lines, b, seq, ci), ro)
        ro_ = _residual_at(_column_entries(lines, b, seq, ci, old_override), ro)
        rid_new = _row_identities_hold(lines, b, seq, ro)
        l_ = sce.get(tuple(k))
        saved = {}
        for kk, oo, nn, _m in diffs:
            ll = sce.get(tuple(kk))
            if ll is not None and oo is not None and kk[0] == b and kk[1] == seq and kk[2] == ro:
                saved[id(ll)] = ll.value_won; ll.value_won = oo
        rid_old = _row_identities_hold(lines, b, seq, ro)
        for kk, oo, nn, _m in diffs:
            ll = sce.get(tuple(kk))
            if ll is not None and id(ll) in saved:
                ll.value_won = saved[id(ll)]
        out["ROWID new=%s old=%s" % (rid_new, rid_old)] += 1
        f1 = lambda r: "0" if r == 0 else ("None" if r is None else "x")
        tag = "new=" + f1(rn) + " old=" + f1(ro_)
        out[tag] += 1
        out[("RF+ROW", tag, rid_new, rid_old)] += 1
        out[("ALL", rc, tuple(k), o, n, tuple(_), tag, rid_new, rid_old)] += 1
        worse_rf = tag in ("new=x old=0",) ; worse_row = (not rid_new) and rid_old
        better_rf = tag == "new=0 old=x"; better_row = rid_new and not rid_old
        if (worse_rf and better_row) or (worse_row and better_rf): out[("MIXED", rc, tuple(k), o, n, tuple(_), tag, "row_new=%s row_old=%s" % (rid_new, rid_old))] += 1
        if (worse_rf and not better_row) or (worse_row and not better_rf): out[("BAD", rc, tuple(k), o, n, tuple(_), tag, "row_new=%s row_old=%s" % (rid_new, rid_old))] += 1
    return out

if __name__ == "__main__":
    items = []
    for l in open(sys.argv[2]):
        r = json.loads(l)
        if r["diffs"]:
            items.append((r["rcept"], r["diffs"]))
    tot = collections.Counter()
    with Pool(6) as p:
        for c in p.imap_unordered(check, items):
            tot.update(c)
    for k, v in tot.items():
        print(k, v) if isinstance(k, tuple) else None
    print({k: v for k, v in tot.items() if not isinstance(k, tuple)})
