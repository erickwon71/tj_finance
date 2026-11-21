#!/usr/bin/env python
"""Full reload of one fiscal year of the periodic universe (body + notes + table meta + biz tables).

Why: the quality work (R0-2, verification, Gate B) is extended one fiscal year at a time towards the
past (TODO A-5, user decision 2026-11-21). Before a year joins the verification scope its filings
must be loaded with the CURRENT parsers: layer 2 body + note_lines + report_tables meta
(`ops._reload_rcept`) and the biz tables with their layer-3 rebuild (`ops._reload_biz`). Years before
2015 were loaded long ago with older parsers and never got note_lines / biz tables at all.

Universe: the verification universe (active KOSPI/KOSDAQ common stock, coverage_class='periodic', no
stock_code starting with '9') x filings of report_type annual/half/quarter, period FY/H1/Q1/Q3 of the
given fiscal year, with the extension notices left out (same rule as `ops.init_era`).

Parallel: shards by corp (`int(corp_code) % n`), because the biz layer-3 rebuild replaces a whole
(corp, fiscal_year). Each shard process logs one line per filing; a rerun skips filings already
`done` in the log (`--resume`), the stores are delete-then-insert per filing anyway (idempotent).
It does NOT use `ops.batch_reload` (that needs a clean, pushed HEAD and a fix batch).

    python scripts/reload_fiscal_year_full.py --fy 2014 --dry-run
    python scripts/reload_fiscal_year_full.py --fy 2014 --limit 30 --workers 1         # pilot
    python scripts/reload_fiscal_year_full.py --fy 2014 --workers 6 --sd-mirror        # full

The layer-3 rebuild of std_financials_v3 is a separate step (`build_std_v3.py --year-min <fy>`).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from multiprocessing import Process
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import engine
from fin2.verification import ops

LOG_DIR = Path(__file__).resolve().parents[1] / "logs" / "reload_fy"


def target_filings(fy: int) -> list[tuple[str, str, str, str]]:
    """(rcept_no, corp_code, fiscal_period, report_type) of the year, ordered by corp then rcept."""
    with engine.connect() as c:
        c.execute(text(f"CREATE TEMP TABLE _u AS {ops._UNIVERSE_SQL}"))
        rows = c.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_period, f.report_type
            FROM filings f JOIN _u USING (corp_code)
            WHERE f.report_type IN ('annual', 'half', 'quarter')
              AND f.fiscal_period IN ('Q1', 'H1', 'Q3', 'FY')
              AND f.fiscal_year = :fy
              AND (f.report_nm IS NULL OR position('제출기한연장신고서' IN f.report_nm) = 0)
            ORDER BY f.corp_code, f.rcept_no"""), {"fy": fy}).fetchall()
    return [tuple(r) for r in rows]


def _done_set(fy: int) -> set[str]:
    done: set[str] = set()
    for p in LOG_DIR.glob(f"fy{fy}_shard*.log"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) >= 4 and parts[1] == "ALL_DONE":
                done.add(parts[2])
    return done


def run_shard(fy: int, shard: int, n: int, filings: list, use_sd: bool, reason: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    mine = [f for f in filings if int(f[1]) % n == shard]
    tally = {"done": 0, "deferred": 0, "failed": 0}
    t0 = time.time()
    with open(LOG_DIR / f"fy{fy}_shard{shard}.log", "a", encoding="utf-8") as log:
        for i, (rcept, corp, period, rtype) in enumerate(mine, 1):
            res = {}
            for kind, fn in (("report", ops._reload_rcept), ("biz", ops._reload_biz)):
                try:
                    res[kind] = fn(rcept, reason, use_sd=use_sd)
                except Exception as exc:          # one bad filing must not stop the shard
                    res[kind] = ("failed", f"{type(exc).__name__}: {str(exc)[:200]}")
            status = ("done" if all(r[0] == "done" for r in res.values())
                      else "deferred" if any(r[0] == "deferred" for r in res.values()) else "failed")
            tally[status] += 1
            # a biz 'failed: no tables' (e.g. a filing without a business section) is not a reload failure
            tag = "ALL_DONE" if status == "done" else "PARTIAL"
            log.write(f"{datetime.now():%H:%M:%S}\t{tag}\t{rcept}\t{corp}\t{period}\t"
                      f"report={res['report'][0]}:{res['report'][1] or ''}\t"
                      f"biz={res['biz'][0]}:{res['biz'][1] or ''}\n")
            log.flush()
            if i % 50 == 0:
                print(f"shard {shard}: [{i}/{len(mine)}] {tally} {time.time() - t0:.0f}s", flush=True)
    print(f"shard {shard} finished: {tally} of {len(mine)} in {time.time() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fy", type=int, required=True, help="fiscal year to load")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="first N filings (pilot)")
    ap.add_argument("--corp", help="comma separated corp_code (test)")
    ap.add_argument("--sd-mirror", action="store_true", help="read the XML from the SD mirror")
    ap.add_argument("--resume", action="store_true", help="skip filings already ALL_DONE in the logs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    filings = target_filings(args.fy)
    if args.corp:
        keep = {c.strip() for c in args.corp.split(",")}
        filings = [f for f in filings if f[1] in keep]
    if args.resume:
        done = _done_set(args.fy)
        filings = [f for f in filings if f[0] not in done]
    if args.limit:
        filings = filings[: args.limit]
    corps = {f[1] for f in filings}
    print(f"FY{args.fy}: {len(filings)} filings of {len(corps)} corps", flush=True)
    if args.dry_run or not filings:
        return
    reason = f"A-5 FY{args.fy} full reload"
    procs = [Process(target=run_shard, args=(args.fy, i, args.workers, filings, args.sd_mirror, reason))
             for i in range(args.workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
