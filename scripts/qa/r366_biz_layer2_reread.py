"""R366: re-read layer-2 biz tables (biz_section_tables) of filings read before R246 (2026-10-17)
whose stored cells show stacked amounts glued together ("167,33423,018" from "167,334&cr;23,018").

Default is a dry run (A/B: stored grids vs the current reader, nothing written). --write stores the
re-read rows per filing (store_biz_raw_tables, rcept_no delete-then-insert, same as the daily).

usage:
    python scripts/qa/r366_biz_layer2_reread.py --out /tmp/x.csv
    python scripts/qa/r366_biz_layer2_reread.py --write --out /tmp/x.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402

_NAS = "/Users/taejin/Project/tj_finance/raw_report/"
_SD = "/Volumes/dart_data/raw_report/"
CANDIDATE_SQL = """
    SELECT DISTINCT b.rcept_no, b.corp_code, f.fiscal_year, f.report_type, dt.file_path
    FROM biz_section_tables b
    JOIN filings f USING (rcept_no)
    JOIN download_tasks dt ON dt.rcept_no = b.rcept_no AND dt.status = 'completed' AND dt.file_type = 'xml'
    WHERE b.fetched_at < '2026-10-17'
      AND b.grid::text ~ '[0-9],[0-9]{3}[0-9]{1,3},[0-9]{3}'
    ORDER BY 1
"""


def _read(job: tuple) -> dict:
    from collector.raw_paths import on_disk
    from fin2.layer2.biz_raw_tables import extract_biz_raw_tables
    rcept, corp, fy, rtype, fp = job
    path = None
    for cand in ((fp.replace(_NAS, _SD) if fp.startswith(_NAS) else None), fp):
        if cand:
            try:
                p = on_disk(cand)
                if p.exists():
                    path = p
                    break
            except OSError:
                continue
    if path is None:
        return {"rcept_no": rcept, "error": "no file"}
    try:
        rows = extract_biz_raw_tables(path, corp, fy, rtype)
    except Exception as exc:  # noqa: BLE001
        return {"rcept_no": rcept, "error": f"{type(exc).__name__}: {exc}"}
    return {"rcept_no": rcept, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    with get_session() as s:
        jobs = [tuple(r) for r in s.execute(text(CANDIDATE_SQL)).fetchall()]
    print(f"[r366] {len(jobs)} filings", flush=True)
    stats = {"filings": 0, "changed": 0, "same": 0, "error": 0, "written": 0}
    with open(args.out, "w", newline="") as fh, ProcessPoolExecutor(args.workers) as ex:
        w = csv.writer(fh)
        w.writerow(["rcept_no", "status", "old_tables", "new_tables", "changed_grids", "domains"])
        for k, res in enumerate(ex.map(_read, jobs, chunksize=4), 1):
            rc = res["rcept_no"]
            stats["filings"] += 1
            if "error" in res:
                stats["error"] += 1
                w.writerow([rc, "error:" + res["error"][:80], "", "", "", ""])
                continue
            new_rows = res["rows"]
            with get_session() as s:
                old = s.execute(text("SELECT table_ord, domain, grid FROM biz_section_tables "
                                     "WHERE rcept_no=:r ORDER BY table_ord"), {"r": rc}).fetchall()
                old_g = {(o.table_ord): json.dumps(o.grid, ensure_ascii=False) for o in old}
                new_g = {r["table_ord"]: json.dumps(r["grid"], ensure_ascii=False) for r in new_rows}
                changed = [t for t in set(old_g) | set(new_g) if old_g.get(t) != new_g.get(t)]
                doms = sorted({r["domain"] for r in new_rows if r["table_ord"] in changed}
                              | {o.domain for o in old if o.table_ord in changed})
                status = "changed" if changed or len(old) != len(new_rows) else "same"
                stats[status] += 1
                if args.write and status == "changed":
                    from fin2.layer2.biz_raw_tables import store_biz_raw_tables
                    store_biz_raw_tables(s, rc, new_rows)
                    s.commit()
                    stats["written"] += 1
            w.writerow([rc, status, len(old), len(new_rows), len(changed), "|".join(doms)])
            if k % 200 == 0:
                print(f"[r366] {k}/{len(jobs)} {stats}", flush=True)
    print(f"[r366] done {stats}", flush=True)


if __name__ == "__main__":
    main()
