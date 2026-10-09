"""R0-2 migration stage 3 — rewrite report_lines with printed values + layer3_cell_corrections.

Body only: the rules never touch note cells except the R159 typo list, and those filings go
through the normal full reload (`fin2.verification.ops._reload_rcept`). Table meta
(`report_tables`) does not depend on cell values and is left as is.

Safety: a filing is rewritten only when its DB body equals what the current code produces with the
rules on (= the reload changes exactly the corrected cells). Anything else (stale load, another
extraction path) is skipped with status 'drift' and listed for a separate decision.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/reload_as_printed.py <rcepts.txt> <out.jsonl> [workers]
Resumable: rcepts already in <out.jsonl> are skipped.
"""
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, os.getcwd())

SD, NAS_MARK = "/Volumes/dart_data/raw_report", "/raw_report/"
REASON = "r0_2_migration"


def work(rc):
    from loguru import logger
    logger.remove()
    from sqlalchemy import text
    from collector.db import get_session
    from fin2.extract import as_printed as AP
    from fin2.extract import layer3_corrections as L3
    from fin2.extract.report_lines import _is_loadable, store_report_lines
    try:
        if rc in L3._typo_rcepts():
            from fin2.verification.ops import _reload_rcept
            st, err = _reload_rcept(rc, REASON, use_sd=True)
            return {"rcept": rc, "status": f"full_{st}", "err": err}
        with get_session() as s:
            t = s.execute(text("""
                SELECT dt.file_path, dt.file_type, f.corp_code, f.fiscal_year, f.fiscal_period,
                       f.period_end_date
                FROM download_tasks dt JOIN filings f USING (rcept_no)
                WHERE dt.rcept_no = :r AND dt.status = 'completed'
                  AND dt.file_type IN ('xml', 'xbrl_zip') AND dt.file_path IS NOT NULL
                ORDER BY (dt.file_type = 'xml') DESC, dt.id DESC LIMIT 1"""), {"r": rc}).fetchone()
            if t is None:
                return {"rcept": rc, "status": "nosource"}
            path = t.file_path
            if t.file_type == "xml" and NAS_MARK in path:
                sd = SD + "/" + path.split(NAS_MARK, 1)[1]
                if Path(sd).exists():
                    path = sd
            if t.file_type == "xml":
                from fin2.extract.sce_dated_anchors import load_prior_evidence
                pb, pi = load_prior_evidence(s, t.corp_code, rc)
                lines, corr = L3.extract_xml_with_corrections(
                    path, rcept_no=rc, corp_code=t.corp_code, report_fiscal_year=t.fiscal_year,
                    report_fiscal_period=t.fiscal_period, include_notes=False,
                    prior_balances=pb, prior_income=pi)
            else:
                lines, corr = L3.extract_xbrl_with_corrections(
                    path, rcept_no=rc, corp_code=t.corp_code, report_fiscal_year=t.fiscal_year,
                    report_fiscal_period=t.fiscal_period, period_end_date=t.period_end_date)
            if not lines:
                return {"rcept": rc, "status": "empty"}
            # drift guard: DB must equal printed + corrections (= the old rules-on output)
            expect = {}
            for l in lines:
                if l.statement != "note" and _is_loadable(l):
                    expect.setdefault(L3._key(l), l.value_won)
            for c in corr:
                k = tuple(c[f] for f in L3._KEY_FIELDS) + (c["label_raw"] or "",)
                if c["kind"] == "drop":
                    expect.pop(k, None)
                else:
                    expect[k] = c["corrected_value"]
            db = {}
            for r in s.execute(text(f"""
                    SELECT {', '.join(L3._KEY_FIELDS)}, label_raw, value_won
                    FROM report_lines WHERE rcept_no = :r"""), {"r": rc}):
                db.setdefault(tuple(r[:-2]) + ((r[-2] or ""),), r[-1])
            if db != expect:
                diff = [[list(k), db.get(k, "absent"), expect.get(k, "absent")]
                        for k in set(db) | set(expect) if db.get(k, "absent") != expect.get(k, "absent")]
                return {"rcept": rc, "status": "drift", "n": len(diff), "diff": diff[:20]}
            if not corr:
                return {"rcept": rc, "status": "nochange"}
            s.execute(text("SELECT set_config('verification.load_reason', :r, true)"), {"r": REASON})
            store_report_lines(s, rc, lines)
            n = L3.store_layer3_corrections(s, rc, corr)
        return {"rcept": rc, "status": "done", "corrections": n, "computed": len(corr)}
    except Exception as e:
        return {"rcept": rc, "status": f"err {type(e).__name__}: {str(e)[:300]}"}


def main():
    src, out_path = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    rcepts = [l.strip() for l in open(src) if l.strip()]
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["rcept"] for l in open(out_path)}
    rcepts = [r for r in rcepts if r not in done]
    print("targets", len(rcepts), flush=True)
    tally = {}
    with Pool(workers) as pool, open(out_path, "a") as fo:
        for i, res in enumerate(pool.imap_unordered(work, rcepts, chunksize=2), 1):
            fo.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
            fo.flush()
            st = res["status"].split(":")[0]
            tally[st] = tally.get(st, 0) + 1
            if i % 500 == 0:
                print(i, tally, flush=True)
    print("done", tally, flush=True)


if __name__ == "__main__":
    main()
