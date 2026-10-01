"""Nightly dump of the verification schema, streamed straight to NAS. Keeps the newest 30.
Months of verdicts live only in the DB, so this is the safety net the markdown issue log
used to be.

Must be launchd's DIRECT entry point (not invoked via a bash script) — under launchd, TCC
attributes file-access checks to whichever process launchd spawned at the top of the job's
tree, not to the specific binary doing the write. `/bin/bash` has no Full Disk Access grant
for the NAS (SMB) volume, so a python child spawned FROM bash still gets EPERM even though
this exact interpreter has its own grant (confirmed empirically 2026-10-01 — see memory
launchd-tcc-nas-blocked). Hence a dedicated plist (com.tjfinance.vqbackup) that runs this
file directly, instead of folding the call into morning_digest.sh's bash job.

usage:
  python scripts/vq_backup.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEST = Path("/Volumes/tj_finance_data/db_backups/verification")
KEEP = 30


def _pg_dump_bin() -> str:
    return shutil.which("pg_dump") or "/opt/homebrew/bin/pg_dump"


def main() -> None:
    mount = DEST if DEST.exists() else DEST.parent
    if not mount.exists():
        print(f"backup FAILED: NAS 미마운트 {DEST} — 마운트 확인 필요", file=sys.stderr)
        sys.exit(2)
    DEST.mkdir(parents=True, exist_ok=True)

    name = f"verification_{datetime.now().strftime('%Y%m%d_%H%M')}.dump"
    dest = DEST / name
    tmp = dest.with_name(dest.name + ".part")

    cmd = [_pg_dump_bin(), "-d", "tj_finance", "-n", "verification", "-Fc"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = 0
    assert proc.stdout is not None
    with open(tmp, "wb") as f:
        while True:
            chunk = proc.stdout.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
    rc = proc.wait()
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""

    if rc != 0 or size == 0:
        tmp.unlink(missing_ok=True)
        print(f"backup FAILED: rc={rc} {stderr.strip()[:300]}", file=sys.stderr)
        sys.exit(1)

    tmp.rename(dest)
    removed = 0
    for old in (sorted(DEST.glob("verification_*.dump"))[:-KEEP] if KEEP > 0 else []):
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass

    print(f"backup ok: {dest} ({size / 1e6:,.1f} MB)"
          + (f" · 회전삭제 {removed}개" if removed else ""))


if __name__ == "__main__":
    main()
