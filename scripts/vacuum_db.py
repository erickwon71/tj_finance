"""A4b / D5 · Weekly VACUUM (ANALYZE) — routine bloat control.

Expert review §5: the big tables (then fact_v2; now note_lines / report_lines) sit at
~13-15% dead tuples, below autovacuum's default 20% trigger, and had no manual VACUUM
history. This script is the explicit weekly backstop (also re-computes planner stats
via ANALYZE, useful after large collect/reload batches).
(2026-10-03: found uninstalled since 2026-07-19; fact_v2 itself was dropped 2026-09-01.)

Uses `vacuumdb` (not raw SQL) because VACUUM cannot run inside a transaction
block, and this matches the project's existing pattern of shelling out to
Postgres client binaries (see backup_db.py / pg_dump).

usage:
  python scripts/vacuum_db.py                 # VACUUM ANALYZE whole DB
  python scripts/vacuum_db.py --table report_lines  # just one table
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

DEFAULT_DB = "tj_finance"


def _bin(name: str) -> str:
    return shutil.which(name) or f"/opt/homebrew/bin/{name}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--table", default=None, help="특정 테이블만(기본: DB 전체)")
    args = ap.parse_args()

    cmd = [_bin("vacuumdb"), "--analyze", "-d", args.db]
    if args.table:
        cmd += ["-t", args.table]

    logger.info(f"[vacuum] 시작 — {'전체 DB' if not args.table else args.table}")
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - t0

    if r.returncode != 0:
        err = f"실패(rc={r.returncode}, {elapsed:,.0f}초): {r.stderr.strip()[:500]}"
        logger.error(f"[vacuum] {err}")
        from scripts.notify import notify_failure
        notify_failure("주간 VACUUM 실패", err)
        sys.exit(1)

    logger.success(f"[vacuum] 완료 — {elapsed:,.0f}초")


if __name__ == "__main__":
    main()
