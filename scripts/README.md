# scripts/

Operational scripts, split into the **recurring main pipeline / ops** (this
directory) and **archived one-off / historical** scripts (`archive/`).

> The main daily pipeline runs via launchd → `collect_new.py`. Nothing in
> `archive/` is scheduled or imported by the main pipeline. See the safety
> notes at the bottom before moving anything.

## Recurring / main pipeline (this directory)

### Scheduled by launchd (`deploy/launchd/*.plist`) — do not move
| Script | Role |
|---|---|
| `collect_new.py` | **Main daily driver**: detect recent filings → download → fin2 E→R→S per corp → supplemental collectors → valuation refresh. |
| `dq_nightly.py` | Nightly data-quality assertions. |
| `backup_db.py` | Nightly logical `pg_dump` backup (NAS). |
| `vacuum_db.py` | Nightly VACUUM/maintenance. |
| `restore_drill.py` | Periodic restore-drill (backup integrity check). |

### Runtime dependencies of the pipeline — do not move
| Script | Imported by |
|---|---|
| `gateb_audit.py` | `collect_new.py` (Gate B audit) |
| `verify_corp_sequential.py` | `collect_new.py` |
| `refresh_valuation_daily.py` | `collect_new.py` |
| `validate_downloads.py` | `verify_corp_sequential.py` (Gate A `integrity_reason`) |
| `diag_calendar_orphans.py` | `dq_assertions.py` (`_ORPHAN_PRED`) |
| `dq_assertions.py` | `dq_nightly.py` |
| `notify.py` | backup/vacuum/dq/restore scripts (failure alerts) |

### Recurring collectors & refreshes (run on demand / chained)
`fin2_sync_prices_daily.py`, `fin2_sync_prices_naver.py`, `fin2_market_cap_daily.py`,
`collect_shareholders.py`, `collect_executives.py`, `collect_industry.py`,
`collect_biz_metrics.py`, `collect_order_backlog.py`, `backfill_capital_events.py`
(idempotent upsert), `verify_cross_source.py`.

### QA harness
`qa/` — repeatable QA sweep / checklist / shard builders.

## archive/ — one-off & historical (not scheduled, not imported by main pipeline)

| Folder | Contents |
|---|---|
| `archive/def4/` | DEF-4 defect repair series (Q1 duplicate-column fix). One-shot. |
| `archive/gateb/` | Gate B remediation/probe/diag scripts (excludes `gateb_audit.py`). |
| `archive/diag/` | Investigation/diagnostic scripts (excludes `diag_calendar_orphans.py`). |
| `archive/backfill/` | fin2 re-extract / backfill / remap batch jobs + `dart_backfill_chain.sh`. Historical backfills; the recurring path now lives in `collect_new.py` / `run.py fin2-all`. |
| `archive/coverage/` | Coverage / completeness / triage checkers (regenerate the `.txt` dumps in the external archive). |
| `archive/legacy/` | Legacy engine runner `run_pipeline.sh` (parse→aggregate path, superseded by fin2). |

### Running an archived script
Archived scripts were moved into subfolders, so their `sys.path`/repo-root
resolution no longer resolves standalone. Run them from the repo root with the
project on the path:

```
PYTHONPATH=. .venv_tj_finance/bin/python scripts/archive/<folder>/<script>.py
```

## Safety notes (before moving any script)
- Anything referenced in `deploy/launchd/*.plist` must keep its path.
- Check cross-imports first: `grep -rn "from scripts\.\|import scripts\." scripts/`
  and bare sibling imports (some scripts import siblings via `sys.path[0]`).
