#!/bin/bash
# Manual/terminal entry point for the verification-schema backup. The actual nightly run is
# scripts/vq_backup.py via the com.tjfinance.vqbackup launchd job, which runs python directly
# (not through this bash script) — a bash-rooted launchd job has no TCC grant for the NAS
# (SMB) volume, and a python child spawned from it inherits that block even though python
# itself holds its own Full Disk Access grant (confirmed empirically 2026-10-01, memory
# launchd-tcc-nas-blocked). This wrapper is fine to run by hand from Terminal, which already
# has that TCC grant.
exec /Users/taejin/Project/tj_finance/.venv/bin/python /Users/taejin/Project/tj_finance/scripts/vq_backup.py
