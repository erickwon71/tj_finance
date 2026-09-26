"""One-time backfill: null out fix_batch_id on open/reopened issues that still point at an
already-finished fix batch (status done/abandoned).

Context: docs/qa/handoff_2026-09-26_full_automation.md §5 described this as an 18-issue
manual-cleanup nuisance from one admin session. A full scan on 2026-09-26 found the real
scope is 11,949 of 12,168 open/reopened issues (98%) — the standard reopen path (batch marked
done, then a later full comparison finds a cell still wrong and reopens the issue) hits this
every time. The schema fix in fin2/verification/schema.sql (trg_issue_before) stops new cases;
this script clears the pre-existing backlog with the identical condition the trigger now
enforces going forward.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from fin2.verification.ops import _Tx, engine  # noqa: E402

CONDITION = """
    status IN ('open', 'reopened') AND fix_batch_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM verification.fix_batches b
                     WHERE b.batch_id = verification.issues.fix_batch_id
                       AND b.status IN ('open', 'waiting_decision', 'reloading'))
"""


def main() -> None:
    with engine.connect() as conn:
        before = conn.execute(text(f"SELECT count(*) FROM verification.issues WHERE {CONDITION}")).scalar_one()
    print(f"대상 {before}건")
    if before == 0:
        return
    with _Tx(evidence="backfill_stale_fix_batch_id_2026-09-26: "
                       "reopened/open with a fix_batch_id pointing at an already-finished batch") as conn:
        n = conn.execute(text(f"UPDATE verification.issues SET fix_batch_id = NULL WHERE {CONDITION}")).rowcount
    print(f"정리 완료: {n}건")


if __name__ == "__main__":
    main()
