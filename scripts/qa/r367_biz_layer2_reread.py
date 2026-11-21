"""R367 / R366-b: re-read biz layer 2 (biz_section_tables) of filings whose stored cells show a stacked
or wrapped value (a value-only cell with a line break) or broken thousands grouping, with the
current biz reader (pre-pass keeps item lines in stacked rows; raw newline in value cells = space).

Dry run by default: compares stored grids with the re-read ones and classifies every changed cell.
--write stores changed filings (store_biz_raw_tables, rcept_no delete-then-insert, as the daily).

usage:
    python scripts/qa/r367_biz_layer2_reread.py --out x.csv [--write] [--workers 4]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402

_NAS = "/Users/taejin/Project/tj_finance/raw_report/"
_SD = "/Volumes/dart_data/raw_report/"
CANDIDATE_SQL = r"""
    SELECT DISTINCT b.rcept_no, b.corp_code, f.fiscal_year, f.report_type, dt.file_path
    FROM biz_section_tables b
    JOIN filings f USING (rcept_no)
    JOIN download_tasks dt ON dt.rcept_no = b.rcept_no AND dt.status = 'completed' AND dt.file_type = 'xml'
    WHERE b.grid::text ~ '"[0-9,.()% △−-]*[0-9][0-9,.()% △−-]*(\\n[0-9,.()% △−-]*)+"'
       OR b.grid::text ~ '"\(?-?[0-9]{4,},[0-9]'
       OR b.grid::text ~ ',[0-9]{4,}[,")]'
       OR b.grid::text ~ '[0-9],[0-9]{1,2}[,"]'
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
        return {"rcept_no": rcept, "rows": extract_biz_raw_tables(path, corp, fy, rtype)}
    except Exception as exc:  # noqa: BLE001
        return {"rcept_no": rcept, "error": f"{type(exc).__name__}: {exc}"}


def _kind(old: str, new: str) -> str:
    if old.replace("\n", "") == new.replace("\n", "") and "\n" in new:
        return "lines_kept"            # R367: R224-joined label/value now keeps its lines
    if "\n" in old and old.replace("\n", " ") == new:
        return "raw_newline_space"     # R366-b
    if re.sub(r"\s", "", old) == re.sub(r"\s", "", new):
        return "whitespace_only"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    with get_session() as s:
        jobs = [tuple(r) for r in s.execute(text(CANDIDATE_SQL)).fetchall()]
    print(f"[r367] {len(jobs)} filings", flush=True)
    stats = collections.Counter()
    kinds = collections.Counter()
    with open(args.out, "w", newline="") as fh, ProcessPoolExecutor(args.workers) as ex:
        w = csv.writer(fh)
        w.writerow(["rcept_no", "status", "old_tables", "new_tables", "changed_cells", "kinds", "example_other"])
        for k, res in enumerate(ex.map(_read, jobs, chunksize=4), 1):
            rc = res["rcept_no"]
            if "error" in res:
                stats["error"] += 1
                w.writerow([rc, "error:" + res["error"][:80], "", "", "", "", ""])
                continue
            new_rows = res["rows"]
            with get_session() as s:
                old = s.execute(text("SELECT table_ord, grid FROM biz_section_tables WHERE rcept_no=:r "
                                     "ORDER BY table_ord"), {"r": rc}).fetchall()
                old_g = {o.table_ord: o.grid for o in old}
                new_g = {r["table_ord"]: r["grid"] for r in new_rows}
                fk = collections.Counter()
                example = ""
                for t in set(old_g) | set(new_g):
                    a, b = old_g.get(t), new_g.get(t)
                    if a == b:
                        continue
                    if a is None or b is None or len(a) != len(b) or any(len(x) != len(y) for x, y in zip(a, b)):
                        fk["table_shape"] += 1
                        continue
                    for ra, rb in zip(a, b):
                        for ca, cb in zip(ra, rb):
                            if ca != cb:
                                kd = _kind(ca, cb)
                                fk[kd] += 1
                                if kd == "other" and not example:
                                    example = json.dumps([ca[:60], cb[:60]], ensure_ascii=False)
                status = "changed" if fk or len(old) != len(new_rows) else "same"
                stats[status] += 1
                kinds.update(fk)
                if args.write and status == "changed":
                    from fin2.layer2.biz_raw_tables import store_biz_raw_tables
                    store_biz_raw_tables(s, rc, new_rows)
                    s.commit()
                    stats["written"] += 1
            w.writerow([rc, status, len(old), len(new_rows), sum(fk.values()),
                        "|".join(f"{a}:{b}" for a, b in sorted(fk.items())), example])
            if k % 1000 == 0:
                print(f"[r367] {k}/{len(jobs)} {dict(stats)} {dict(kinds)}", flush=True)
    print(f"[r367] done {dict(stats)} cells {dict(kinds)}", flush=True)


if __name__ == "__main__":
    main()
