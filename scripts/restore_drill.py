"""A1b · Backup restore drill — proves a dump is actually restorable, not just present.

Restores the newest `*.dump` from the backup dir into a throwaway DB
(`tj_finance_restore_test`), then spot-checks row counts against the live DB
for the tables that carry data in the backup (fact_v2 data is excluded by
backup_db.py, so it's expected to be empty — schema-only — after restore).

usage:
  python scripts/restore_drill.py                    # use newest dump, keep scratch DB
  python scripts/restore_drill.py --dump <path.dump>  # restore a specific dump
  python scripts/restore_drill.py --drop-after        # drop the scratch DB when done
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from loguru import logger

LIVE_DB = "tj_finance"
SCRATCH_DB = "tj_finance_restore_test"
BACKUP_DIR = Path("/Volumes/dart_data/db_backups")

# tables expected to carry real data in the (default, non --full) backup.
DATA_TABLES = [
    "corporations",
    "std_financials_v2",
    "std_financials_calendar",
    "stock_prices",
    "statement_source",
    "executives",
    "filings",
    "face_audit",
    "face_line_audit",
    "verification_results",
]
# excluded from backup data (schema only) — expected 0 rows after restore.
SCHEMA_ONLY_TABLES = ["fact_v2"]


def _bin(name: str) -> str:
    return shutil.which(name) or f"/opt/homebrew/bin/{name}"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    logger.info(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _count(db: str, table: str) -> int | None:
    r = _run([_bin("psql"), "-d", db, "-Atc", f"select count(*) from {table};"])
    if r.returncode != 0:
        logger.warning(f"[{db}.{table}] count failed: {r.stderr.strip()[:200]}")
        return None
    return int(r.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", help="restore this dump file (default: newest in backup dir)")
    ap.add_argument("--drop-after", action="store_true", help="drop the scratch DB when done")
    args = ap.parse_args()

    if args.dump:
        dump_path = Path(args.dump)
    else:
        dumps = sorted(BACKUP_DIR.glob(f"{LIVE_DB}_*.dump"))
        if not dumps:
            logger.error(f"[drill] no dumps found in {BACKUP_DIR}")
            sys.exit(2)
        dump_path = dumps[-1]

    if not dump_path.exists():
        logger.error(f"[drill] dump not found: {dump_path}")
        sys.exit(2)
    logger.info(f"[drill] using dump: {dump_path} ({dump_path.stat().st_size / 1e6:,.1f} MB)")

    logger.info(f"[drill] dropping/creating scratch DB {SCRATCH_DB}")
    _run([_bin("dropdb"), "--if-exists", SCRATCH_DB])
    r = _run([_bin("createdb"), SCRATCH_DB])
    if r.returncode != 0:
        logger.error(f"[drill] createdb failed: {r.stderr.strip()[:500]}")
        sys.exit(1)

    logger.info(f"[drill] pg_restore → {SCRATCH_DB} (this can take a few minutes)")
    r = _run([_bin("pg_restore"), "-d", SCRATCH_DB, "--no-owner", "--no-privileges", str(dump_path)])
    if r.returncode != 0:
        # pg_restore often exits nonzero on benign warnings (e.g. missing extensions/roles);
        # surface stderr so the user can judge, but don't abort the drill on that alone.
        logger.warning(f"[drill] pg_restore reported issues (rc={r.returncode}):\n{r.stderr.strip()[:2000]}")

    logger.info("[drill] row-count spot-check: live vs restored")
    ok = True
    for table in DATA_TABLES:
        live = _count(LIVE_DB, table)
        restored = _count(SCRATCH_DB, table)
        status = "OK" if live is not None and live == restored else "MISMATCH"
        if status != "OK":
            ok = False
        logger.info(f"  {table:28s} live={live!s:>10} restored={restored!s:>10}  {status}")

    for table in SCHEMA_ONLY_TABLES:
        restored = _count(SCRATCH_DB, table)
        status = "OK (schema-only, 0 rows expected)" if restored == 0 else f"UNEXPECTED ({restored} rows)"
        if restored != 0:
            ok = False
        logger.info(f"  {table:28s} restored={restored!s:>10}  {status}")

    if args.drop_after:
        logger.info(f"[drill] dropping scratch DB {SCRATCH_DB}")
        _run([_bin("dropdb"), "--if-exists", SCRATCH_DB])

    if ok:
        logger.success("[drill] PASS — dump restores cleanly and row counts match live.")
    else:
        logger.error("[drill] FAIL — see mismatches above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
