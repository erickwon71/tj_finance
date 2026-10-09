"""R0-2 migration stage 0 — what changes when layer 2 stops changing printed values.

For each filing: extract with every value-changing step on (TRACE attributes each changed cell
to the step that changed it), extract again with all steps off (= as printed), and compare the
as-printed lines with the DB (= what a reload would change). DB is never written.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/measure_as_printed.py <rcepts.txt|all> <out.jsonl> [workers] [shard_i shard_n]
Output: one JSON line per filing that has any difference (or an error).
"""
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, os.getcwd())

SD, NAS_MARK = "/Volumes/dart_data/raw_report", "/raw_report/"


def _key(l):
    return (l.statement, l.basis, l.table_seq, l.row_order, l.col_index, l.is_cumulative, l.period_kind)


def _snap(lines):
    return {_key(l): l.value_won for l in lines}


def _diff(a, b):
    out = []
    for k in set(a) | set(b):
        x, y = a.get(k, "absent"), b.get(k, "absent")
        if x != y:
            out.append([list(k), x, y])
    return out


def _source(cur, rc):
    cur.execute("""select dt.file_path, dt.file_type, f.corp_code, f.fiscal_year, f.fiscal_period, f.period_end_date
                   from download_tasks dt join filings f using (rcept_no)
                   where dt.rcept_no=%s and dt.status='completed' and dt.file_type in ('xml','xbrl_zip')
                     and dt.file_path is not null
                   order by (dt.file_type='xml') desc, dt.id desc limit 1""", (rc,))
    return cur.fetchone()


def work(rc):
    from loguru import logger
    logger.remove()
    import psycopg2
    from fin2.extract import as_printed as AP
    from fin2.extract import report_lines as rl
    from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        t = _source(cur, rc)
        if t is None:
            return {"rcept": rc, "status": "nosource"}
        path, ftype, corp, fy, fp, pe = t
        if ftype == "xml" and NAS_MARK in path:
            sd = SD + "/" + path.split(NAS_MARK, 1)[1]
            if Path(sd).exists():
                path = sd
        if not Path(path).exists():
            return {"rcept": rc, "status": "nopath"}
        if ftype == "xml":
            from collector.db import get_session
            from fin2.extract.sce_dated_anchors import load_prior_evidence
            with get_session() as s:
                pb, pi = load_prior_evidence(s, corp, rc)

            # notes do not feed the body chain (checked: same body with/without notes); only the
            # R159 typo list touches note cells, so notes are extracted for those filings only
            from parser.xml.table_extractor import _SOURCE_TYPO_CELL_FIXES
            with_notes = rc in {k[0] for k in _SOURCE_TYPO_CELL_FIXES}

            def run():
                return rl.extract_report_lines(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                               report_fiscal_period=fp, include_notes=with_notes,
                                               prior_balances=pb, prior_income=pi)
        else:
            def run():
                return extract_report_lines_xbrl(path, rcept_no=rc, corp_code=corp, report_fiscal_year=fy,
                                                 report_fiscal_period=fp, period_end_date=pe)

        steps = {}
        prev = {}

        def trace(step, lines):
            snap = _snap(lines)
            if step != "_base" and prev:
                d = _diff(prev, snap)
                if d:
                    steps.setdefault(step, []).extend(d)
            prev.clear()
            prev.update(snap)

        AP.TRACE = trace
        with AP.forced("repaired"):
            on = run()
        AP.TRACE = None
        with AP.forced("printed"):
            off = run()
        if not off:
            return {"rcept": rc, "status": "empty_off", "ftype": ftype}
        on_s = {k: v for k, v in _snap(on).items() if k[0] != "note"}
        off_s = {k: v for k, v in _snap(off).items() if k[0] != "note"}
        total = _diff(on_s, off_s)       # [key, on, off]
        attributed = {tuple(d[0]) for ds in steps.values() for d in ds}
        unattributed = [d for d in total if tuple(d[0]) not in attributed]
        notes = _diff({k: v for k, v in _snap(on).items() if k[0] == "note"},
                      {k: v for k, v in _snap(off).items() if k[0] == "note"})
        # what a reload with the switch off would change in report_lines (DB vs as printed)
        cur.execute("""select statement,basis,table_seq,row_order,col_index,is_cumulative,period_kind,value_won
                       from report_lines where rcept_no=%s""", (rc,))
        db = {tuple(r[:7]): r[7] for r in cur.fetchall()}
        loadable = {k: v for k, v in off_s.items()}
        vs_db = [[list(k), db[k], loadable[k]] for k in db if k in loadable and db[k] != loadable[k]]
        # DB vs the current code with every step on: anything here is drift unrelated to R0-2
        # (stale load, legacy/PDF path) — such filings must not be reloaded blindly
        drift = [[list(k), db[k], on_s[k]] for k in db if k in on_s and db[k] != on_s[k]]
        db_only = sum(1 for k in db if k not in on_s)
        if not (total or notes or vs_db or drift):
            return None
        return {"rcept": rc, "status": "ok", "ftype": ftype, "corp": corp, "fy": fy, "fp": fp,
                "steps": {k: v for k, v in steps.items() if k[0] != "_"},
                "unattributed": unattributed, "notes_changed": len(notes), "vs_db": vs_db,
                "drift": drift[:50], "n_drift": len(drift), "db_only": db_only}
    except Exception as e:
        return {"rcept": rc, "status": f"err {type(e).__name__}: {str(e)[:200]}"}
    finally:
        conn.close()


def _work_keyed(rc):
    return rc, work(rc)


def main():
    import psycopg2
    src, out_path = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    if src in ("all", "2015+"):
        # "2015+" = report fiscal year >= 2015 (migration scope, user decision 2026-10-10;
        # earlier years follow later with the same rules)
        cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
        where = "where report_fiscal_year >= 2015" if src == "2015+" else ""
        cur.execute(f"select distinct rcept_no from report_lines {where} order by 1 desc")
        rcepts = [r[0] for r in cur.fetchall()]
    else:
        rcepts = [l.strip() for l in open(src) if l.strip()]
    if len(sys.argv) > 5:
        i, n = int(sys.argv[4]), int(sys.argv[5])
        rcepts = [r for r in rcepts if int(r) % n == i]
    done = set()
    if os.path.exists(out_path + ".done"):
        done = {l.strip() for l in open(out_path + ".done")}
    rcepts = [r for r in rcepts if r not in done]
    print("targets", len(rcepts), flush=True)
    with Pool(workers) as pool, open(out_path, "a") as fo, open(out_path + ".done", "a") as fd:
        for i, (rc, res) in enumerate(pool.imap_unordered(_work_keyed, rcepts, chunksize=4), 1):
            if res is not None:
                fo.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
                fo.flush()
            if res is None or not res["status"].startswith("err"):
                fd.write(rc + "\n")   # errors stay pending for a resumed run
            if i % 1000 == 0:
                fd.flush()
                print(i, flush=True)
    print("done", len(rcepts), flush=True)


if __name__ == "__main__":
    main()
