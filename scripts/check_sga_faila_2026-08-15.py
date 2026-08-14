"""One-off: run the same Gate B v3 recheck as gateb_audit.py for the Phase 1 (is.sga
override) 46-corp scope, but print the FULL fail_rows list (not just top-20) filtered
to rows whose failing fields include 'sga' or 'cogs' — to verify Phase 1 didn't leave
any sga fail_a/fail_b behind. Read-only (--no-commit passthrough), no DB writes.

Usage: python scripts/check_sga_faila_2026-08-15.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import get_session
import scripts.gateb_audit as ga


def main():
    args = argparse.Namespace(
        source="v3", corp=None,
        corp_file=str(Path(__file__).resolve().parent / "sga_phase1_46corps_2026-08-15.txt"),
        corps=None, sample=None, seed=42, fy_min=2010, fy_max=2100,
        recheck=True, no_commit=True, line_audit=False,
    )
    ga.ensure_table()
    agg = {"status": Counter(), "gate": Counter(), "fld_pass": 0, "fld_fail": 0,
           "fail_rows": [], "errors": 0}
    with get_session() as session:
        corps = ga.select_corps(session, args)
        print(f"대상 corp {len(corps)}사")
        for c in corps:
            ga.audit_corp(session, c, args, agg)

    sga_rows = [r for r in agg["fail_rows"] if "sga" in r[3]]
    cogs_rows = [r for r in agg["fail_rows"] if "cogs" in r[3]]
    print(f"\ntotal fail_rows={len(agg['fail_rows'])}")
    print(f"sga-field fail rows = {len(sga_rows)}")
    for r in sga_rows:
        print(f"  {r}")
    print(f"\ncogs-field fail rows = {len(cogs_rows)}")
    for r in cogs_rows:
        print(f"  {r}")


if __name__ == "__main__":
    main()
