#!/bin/bash
# Nightly dump of the verification schema (tens of MB). Months of verdicts live only in the
# DB, so this is the safety net the markdown issue log used to be. Keeps the newest 30.
set -uo pipefail
DEST="${VQ_BACKUP_DIR:-/Users/taejin/Project/tj_finance/db_backups/verification}"
mkdir -p "$DEST"
out="$DEST/verification_$(date '+%Y%m%d_%H%M').dump"
if pg_dump -d tj_finance -n verification -Fc -f "$out"; then
  ls -1t "$DEST"/verification_*.dump 2>/dev/null | tail -n +31 | xargs -r rm -f
  echo "backup ok: $out ($(du -h "$out" | cut -f1))"
else
  echo "backup FAILED" >&2
  exit 1
fi
