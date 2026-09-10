"""Verify the unit-override mechanism for the 00138516(아남전자 FY2006) case.

docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md

Read-only dry-run of combine_full() (no DB write) — confirms:
  1. col["retained_earnings"] is now the corrected (~2.15e9) value, not the
     declared-unit-oversized (~2.15e15) one.
  2. prov["unit_overrides"] carries the traceability record.

Actual DB backfill happens separately via `scripts/build_std_v3.py --corp 00138516`.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from fin2.layer3.combine import combine_full

CORP = "00138516"
FY = 2006
PERIOD = "FY"


def main():
    with get_session() as session:
        for basis in ("consolidated", "separate"):
            col, conflicts, prov = combine_full(session, CORP, FY, PERIOD, basis)
            print(f"--- basis={basis} ---")
            print("retained_earnings:", col.get("retained_earnings"))
            print("unit_overrides:", prov.get("unit_overrides"))


if __name__ == "__main__":
    main()
