"""A4b / D5 · Weekly VACUUM (ANALYZE) — routine bloat control.

Expert review §5: fact_v2 (87M rows) had ~15% dead tuples and no manual VACUUM
history. `collector/db.py` migration `2026_07_fact_v2_autovacuum_tuning`
lowers fact_v2's autovacuum thresholds so autovacuum itself runs more often;
this script is the explicit weekly backstop (also re-computes planner stats
via ANALYZE, useful after large collect batches).

Uses `vacuumdb` (not raw SQL) because VACUUM cannot run inside a transaction
block, and this matches the project's existing pattern of shelling out to
Postgres client binaries (see backup_db.py / pg_dump).

usage:
  python scripts/vacuum_db.py                 # VACUUM ANALYZE whole DB
  python scripts/vacuum_db.py --table fact_v2  # just one table
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

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
        logger.error(f"[vacuum] 실패(rc={r.returncode}, {elapsed:,.0f}초): {r.stderr.strip()[:1000]}")
        sys.exit(1)

    logger.success(f"[vacuum] 완료 — {elapsed:,.0f}초")


if __name__ == "__main__":
    main()
