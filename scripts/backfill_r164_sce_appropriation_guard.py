"""R164 backfill - re-load filings whose SCE table was dropped by the
appropriation-statement guard (2026-09-22).

Root cause is fixed in `fin2/extract/text.py::_detect_body_statement_tables`
(see docs/PARSING_RULES.md R164). This script re-extracts and re-stores the
already-loaded filings the scanner identified, so the recovered SCE tables
actually reach the DB - retroactive backfill is never automatic
(docs/runbook_new_parser_pipeline_integration.md).

Usage:
    python scripts/backfill_r164_sce_appropriation_guard.py --dry-run
    python scripts/backfill_r164_sce_appropriation_guard.py --apply

Default is dry-run; --apply is required to write.

Target selection is NOT hardcoded: pass the scanner's hit list with
--rcept-list (scripts/scan_r164_sce_appropriation_guard.py --out ...).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.report_lines import (  # noqa: E402
    extract_report_lines, store_report_lines, store_report_tables)

_NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"


def _load_meta(session, rcept_nos: list[str]) -> dict[str, dict]:
    rows = session.execute(text("""
        SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year,
               f.fiscal_period, c.corp_name
        FROM download_tasks dt
        JOIN filings f ON f.rcept_no = dt.rcept_no
        JOIN corporations c ON c.corp_code = f.corp_code
        WHERE dt.rcept_no = ANY(:rs) AND dt.status = 'completed'
          AND dt.file_type = 'xml'
    """), {"rs": rcept_nos}).mappings().all()
    return {r["rcept_no"]: dict(r) for r in rows}


def _sd(path: str, use_sd: bool) -> Path:
    """Bulk XML reads go to the SD card - NAS (SMB) full scans stall."""
    if use_sd and path and path.startswith(_NAS_PREFIX):
        return Path(_SD_PREFIX + path[len(_NAS_PREFIX):])
    return Path(path)


def _loaded_sce_counts(session, rcept_no: str) -> dict[str, int]:
    """SCE rows currently in the DB, per basis.

    ★SCE keeps EVERY col_index - it is not in `_PERIOD_AXIS_STATEMENTS`, whose
    col_index=0-only rule applies to BS/IS/CF. So comparing all extracted SCE
    lines against these counts is apples to apples. (R163's backfill got this
    wrong for CF and reported a 107-cell delta that did not exist; the memory
    note is `feedback-do-not-attribute-backfill-recoveries-to-one-rule`.)
    """
    rows = session.execute(text("""
        SELECT basis, count(*) n FROM report_lines
        WHERE rcept_no = :r AND statement = 'SCE' GROUP BY 1"""),
        {"r": rcept_no}).mappings().all()
    return {r["basis"]: r["n"] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to the DB")
    ap.add_argument("--dry-run", action="store_true", help="explicit no-op (default)")
    ap.add_argument("--rcept-list", type=Path, required=True,
                    help="one rcept_no per line (scanner --out)")
    ap.add_argument("--no-sd", action="store_true",
                    help="read from the NAS path as recorded instead of the SD card")
    ap.add_argument("--overwrite-reviewed", action="store_true",
                    help="also overwrite filings already reviewed as 'pass' "
                         "(R139 guard). Measured for R164: 0 targets are 'pass', "
                         "so this should not be needed - it stays off by default "
                         "and needs explicit user approval to use.")
    args = ap.parse_args()

    rcept_nos = [l.strip() for l in args.rcept_list.read_text().splitlines()
                 if l.strip()]
    print("targets: %d" % len(rcept_nos))

    ok, gained_rows = 0, 0
    blocked: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    no_gain: list[str] = []

    with get_session() as session:
        meta = _load_meta(session, rcept_nos)
        missing = [r for r in rcept_nos if r not in meta]
        if missing:
            print("! no metadata (download incomplete / other file type), skipped: %d"
                  % len(missing))

        for rcept_no in rcept_nos:
            m = meta.get(rcept_no)
            if not m:
                continue
            path = _sd(m["file_path"], not args.no_sd)
            if not path.exists():
                failed.append((rcept_no, "file missing: %s" % path))
                continue
            try:
                lines = extract_report_lines(
                    path, rcept_no=rcept_no, corp_code=m["corp_code"],
                    report_fiscal_year=m["fiscal_year"],
                    report_fiscal_period=m["fiscal_period"], include_notes=False)
            except Exception as exc:                    # noqa: BLE001
                failed.append((rcept_no, "extract failed: %s: %s"
                               % (type(exc).__name__, exc)))
                continue
            if not lines:
                failed.append((rcept_no, "extracted 0 rows"))
                continue

            before = _loaded_sce_counts(session, rcept_no)
            after: dict[str, int] = {}
            for l in lines:
                if l.statement == "SCE":
                    after[l.basis] = after.get(l.basis, 0) + 1
            delta = {b: after.get(b, 0) - before.get(b, 0)
                     for b in set(after) | set(before)}
            gained = sum(v for v in delta.values() if v > 0)
            label = ", ".join("%s %d->%d" % (b, before.get(b, 0), after.get(b, 0))
                              for b in sorted(delta) if delta[b])

            if gained == 0:
                no_gain.append(rcept_no)

            if not args.apply:
                print("[dry-run] %s %-14s %s%-4s SCE %s"
                      % (rcept_no, (m["corp_name"] or "")[:12], m["fiscal_year"],
                         m["fiscal_period"] or "", label or "(no change)"))
                gained_rows += gained
                continue

            try:
                store_report_lines(session, rcept_no, lines,
                                   overwrite_reviewed=args.overwrite_reviewed)
                store_report_tables(session, rcept_no, lines)
                session.commit()
            except ValueError as exc:                   # manual/reviewed guard
                session.rollback()
                blocked.append((rcept_no, str(exc)))
                continue
            ok += 1
            gained_rows += gained
            print("OK %s %-14s SCE %s" % (
                rcept_no, (m["corp_name"] or "")[:12], label or "(no change)"))

    print("\nSCE rows gained: %d" % gained_rows)
    if no_gain:
        print("! no SCE gain on %d filing(s) - these need a look, the scanner "
              "expected a recovery: %s" % (len(no_gain), no_gain[:10]))
    if args.apply:
        print("done: %d reloaded, %d blocked by guard, %d failed"
              % (ok, len(blocked), len(failed)))
    for r in blocked:
        print("  BLOCKED", r)
    for r in failed:
        print("  FAILED", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
