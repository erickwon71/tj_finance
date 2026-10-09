"""R0-2 follow-up (user decision 2026-10-10 morning): fully reload the filings the migration skipped
as 'drift' (DB written by an older parser) with the current code — printed values in layer 2,
rule results in layer3_cell_corrections, notes and table meta rewritten too (ops._reload_rcept).

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/reload_drift.py <rcepts.txt> <out.jsonl> [workers]
Resumable: rcepts already in <out.jsonl> are skipped.
"""
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.getcwd())


def work(rc):
    from loguru import logger
    logger.remove()
    from fin2.verification.ops import _reload_rcept
    try:
        st, err = _reload_rcept(rc, "r0_2_drift_reload", use_sd=True)
        return {"rcept": rc, "status": st, "err": err}
    except Exception as e:
        return {"rcept": rc, "status": f"err {type(e).__name__}: {str(e)[:300]}"}


def main():
    src, out_path = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    rcepts = [l.strip() for l in open(src) if l.strip()]
    if os.path.exists(out_path):
        done = {json.loads(l)["rcept"] for l in open(out_path)}
        rcepts = [r for r in rcepts if r not in done]
    print("targets", len(rcepts), flush=True)
    with Pool(workers) as pool, open(out_path, "a") as fo:
        for res in pool.imap_unordered(work, rcepts):
            fo.write(json.dumps(res, ensure_ascii=False) + "\n")
            fo.flush()
    print("done", flush=True)


if __name__ == "__main__":
    main()
