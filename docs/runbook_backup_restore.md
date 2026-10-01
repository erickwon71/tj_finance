# Runbook — DB Backup & Restore

★2026-10-01: found both the core and verification backup jobs had silently stopped (not
installed in `~/Library/LaunchAgents/` — likely dropped during the July NAS/TCC
troubleshooting and never reinstalled; `logs/backup.err.log` had no entry since 2026-07-20).
Reinstalled both, fixed a TCC gap neither job had hit before (see "launchd TCC gotcha"
below), and gave the verification backup its own job instead of running inline from
`morning_digest.sh`. `fact_v2` references below are historical — it was DROPped 2026-09-01,
so `backup_db.py` has dumped the whole DB (no schema-only exclusion) since then.

## launchd TCC gotcha (read before touching any of these scripts)

Under launchd, a process writing/reading the NAS (SMB) volume needs Full Disk Access — but
**only python has that grant** (`/Library/Developer/CommandLineTools/.../python3.9`, the real
path `.venv/bin/python` resolves to). Confirmed empirically 2026-10-01:
- `pg_dump`/`pg_restore` given a NAS path directly → **always EPERM** under launchd, even as a
  child of the FDA-granted python (no inheritance downward to a child binary).
- that same granted python, run as a **child of `/bin/bash`** (e.g. inline inside
  `morning_digest.sh`, which launchd runs as `/bin/bash -lc ...`) → **also EPERM**, despite
  python's own grant (no inheritance either — each process in the chain needs its own path to
  the NAS that doesn't go through an ungranted binary).
- that same python as **launchd's direct `ProgramArguments[0]`, performing the NAS
  open()/read()/write() itself** → works.

So every NAS-touching job must have python as the literal first `ProgramArguments` entry, and
`pg_dump`/`pg_restore` must never touch the NAS path directly — stream through python instead
(`subprocess.Popen(..., stdout=PIPE)` + python's own `open()`/`write()` for dumps; `open(path,
"rb")` handed to `pg_restore` via `stdin=` for restores). This is why the verification backup
is its own job (`com.tjfinance.vqbackup`) instead of a line inside `morning_digest.sh`.

## Backup

- **Core DB** — job `com.tjfinance.backup` (`~/Library/LaunchAgents/com.tjfinance.backup.plist`), daily 19:00
  (rides the 17:58 `pmset` wake window used by the 18:00 collect job). Script: `scripts/backup_db.py --keep 7`.
  Output: `/Volumes/tj_finance_data/db_backups/tj_finance_full_<timestamp>.dump` on the **NAS (RAID1)** — a
  physical disk independent of the Mac's PGDATA, so the live DB (Mac) and the dump (NAS) are separate failure
  domains (SPOF resolved). NAS not mounted → backup fails with a notification (mount guard). Full dump, custom
  format (no `fact_v2` exclusion since its 2026-09-01 DROP — nothing left to exclude). Rotation: keeps the
  newest 7. Logs: `logs/backup.out.log`, `logs/backup.err.log`.
- **Verification schema** — job `com.tjfinance.vqbackup` (`~/Library/LaunchAgents/com.tjfinance.vqbackup.plist`),
  daily 19:10 (same wake window, right after the core backup). Script: `scripts/vq_backup.py` (the `vq_backup.sh`
  wrapper is for manual/terminal use only — Terminal already has the NAS TCC grant, so it works either way, but
  the *scheduled* run must go through the dedicated python-entry job, not a bash-invoked script — see the TCC
  gotcha above). Output: `/Volumes/tj_finance_data/db_backups/verification/verification_<timestamp>.dump` on
  NAS (moved off local disk 2026-10-01 — it shared the Mac's failure domain there). Rotation: keeps the newest
  30. Logs: `logs/vqbackup.out.log`, `logs/vqbackup.err.log`. `morning_digest.sh`'s "백업" line reports this
  job's last log line; it no longer triggers the backup itself.

**Daily health check** (should show today's date and a nonzero-size dump):
```bash
tail -20 logs/backup.out.log
tail -5 logs/vqbackup.out.log
ls -la /Volumes/tj_finance_data/db_backups/ | tail -5
ls -la /Volumes/tj_finance_data/db_backups/verification/ | tail -5
```

## Restore drill

Proves a dump is actually restorable, not just present.

- Job: `com.tjfinance.restoredrill` (LaunchAgent) — **automatic, quarterly** (Jan/Apr/Jul/Oct 1st, 19:30,
  right after that day's 19:00 backup and before 20:30 dqcheck — minimizes false-positive row-count
  mismatches from writes landing between backup time and drill time). Runs `--drop-after` (cleans up
  the scratch DB automatically). Failure → C10 macOS notification (`scripts/notify.py`).
- Logs: `logs/restoredrill.out.log`, `logs/restoredrill.err.log`
- Can also run manually anytime (e.g. after any change to `backup_db.py`):

```bash
python scripts/restore_drill.py               # restores newest dump into tj_finance_restore_test, keeps it for inspection
python scripts/restore_drill.py --drop-after  # same, but drops the scratch DB when done
python scripts/restore_drill.py --dump /Volumes/tj_finance_data/db_backups/tj_finance_full_20261001_2040.dump  # specific dump
```

What it does:
1. `dropdb --if-exists` + `createdb` a scratch DB `tj_finance_restore_test` (never touches the live `tj_finance` DB)
2. `pg_restore` the dump into it (reads the NAS file itself and hands it to `pg_restore` via stdin — see the
   TCC gotcha above; `pg_restore <path on NAS>` directly would EPERM under launchd)
3. Row-count spot-check on data-bearing tables (`corporations`, `std_financials_v3`, `std_financials_calendar`,
   `stock_prices`, `statement_source`, `executives`, `filings`, `face_audit`, `face_line_audit`,
   `verification_results`) — live vs restored, expect exact match
4. Exits nonzero and prints PASS/FAIL if any table mismatches

Full disaster-recovery restore (overwrites the live DB — only after real data loss, not for drills):
```bash
pg_restore -d tj_finance --clean --if-exists <path.dump>
```

## Actual restore drill log

| Date | Dump used | Result | Notes |
|---|---|---|---|
| 2026-07-04 | `tj_finance_core_20260702_2237.dump` (pre-schedule manual dump) | PASS* | All data tables matched live exactly (`corporations`, `std_financials_v2`, `stock_prices`, `statement_source`, `executives`, `filings`, `face_audit`, `face_line_audit`); `fact_v2` restored schema-only (0 rows) as designed. Script flagged `verification_results` as a MISMATCH (live=695,404, restored=0) — investigated and confirmed benign: those rows were all written 2026-07-03 11:23–12:08, i.e. *after* this dump was taken at 2026-07-02 22:38. Not a backup bug — the dump simply predates that data. Mechanism itself (`pg_restore` + row-count comparison) verified working. |
| _(pending)_ | first dump produced by the 19:00 `com.tjfinance.backup` schedule | | Re-run `restore_drill.py` once tonight's dump exists — this is the real end-to-end validation of the automated pipeline (A1a). |
| 2026-10-01 | both jobs reinstalled after discovering neither had run since 2026-07-20 (not in `~/Library/LaunchAgents/`) | — | Not a drill — jobs were missing, not failing. Core backup manually kickstarted 20:40 as the fresh first dump; verified it and `vq_backup.py` actually write to NAS under real launchd (not Terminal) before trusting the schedule again. `restore_drill.py` itself got a TCC fix (stdin, see above) but has **not been run** against the new dump yet — do that once the 20:40 dump finishes, don't wait for January. |

## Cadence

- Backup: automatic, nightly (see schedule above) — **health-check it occasionally** (`tail logs/backup.err.log`, `tail logs/vqbackup.err.log`); it went silent for 2+ months (2026-07-20 to 2026-10-01) with nothing surfacing the gap until someone asked.
- Restore drill: automatic, quarterly (`com.tjfinance.restoredrill`, C4 — done 2026-07-04), plus the manual run above whenever needed
