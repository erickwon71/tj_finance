# Runbook — DB Backup & Restore

## Backup

- Job: `com.tjfinance.backup` (LaunchAgent, `~/Library/LaunchAgents/com.tjfinance.backup.plist`)
- Schedule: daily 19:00 (rides the 17:58 `pmset` wake window used by the 18:00 collect job)
- Script: `scripts/backup_db.py --keep 7`
- Output: `/Volumes/dart_data/db_backups/tj_finance_core_<timestamp>.dump` (custom format, `fact_v2` data excluded — schema only, ~86GB of reproducible fact data skipped to keep dumps small/fast)
- Rotation: keeps the newest 7 dumps, deletes older ones
- Logs: `logs/backup.out.log`, `logs/backup.err.log`

**Daily health check** (should show today's date and a nonzero-size dump):
```bash
tail -20 logs/backup.out.log
ls -la /Volumes/dart_data/db_backups/ | tail -5
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
python scripts/restore_drill.py --dump /Volumes/dart_data/db_backups/tj_finance_core_20260704_1900.dump  # specific dump
```

What it does:
1. `dropdb --if-exists` + `createdb` a scratch DB `tj_finance_restore_test` (never touches the live `tj_finance` DB)
2. `pg_restore` the dump into it
3. Row-count spot-check on data-bearing tables (`corporations`, `std_financials_v2`, `stock_prices`, `statement_source`, `executives`, `filings`, `face_audit`, `face_line_audit`, `verification_results`) — live vs restored, expect exact match
4. Confirms `fact_v2` restored with 0 rows (schema-only by design — not a failure)
5. Exits nonzero and prints PASS/FAIL if any table mismatches

Full disaster-recovery restore (overwrites the live DB — only after real data loss, not for drills):
```bash
pg_restore -d tj_finance --clean --if-exists <path.dump>
# fact_v2 has no data in the core dump — re-derive it from raw_report:
python run.py fin2-all
```

## Actual restore drill log

| Date | Dump used | Result | Notes |
|---|---|---|---|
| 2026-07-04 | `tj_finance_core_20260702_2237.dump` (pre-schedule manual dump) | PASS* | All data tables matched live exactly (`corporations`, `std_financials_v2`, `stock_prices`, `statement_source`, `executives`, `filings`, `face_audit`, `face_line_audit`); `fact_v2` restored schema-only (0 rows) as designed. Script flagged `verification_results` as a MISMATCH (live=695,404, restored=0) — investigated and confirmed benign: those rows were all written 2026-07-03 11:23–12:08, i.e. *after* this dump was taken at 2026-07-02 22:38. Not a backup bug — the dump simply predates that data. Mechanism itself (`pg_restore` + row-count comparison) verified working. |
| _(pending)_ | first dump produced by the 19:00 `com.tjfinance.backup` schedule | | Re-run `restore_drill.py` once tonight's dump exists — this is the real end-to-end validation of the automated pipeline (A1a). |

## Cadence

- Backup: automatic, nightly (see schedule above)
- Restore drill: automatic, quarterly (`com.tjfinance.restoredrill`, C4 — done 2026-07-04), plus the manual run above whenever needed
