"""One-off: Gate B v3 recheck for the Phase 2 (is.cogs additive override) 19-corp scope,
printing the FULL fail_rows list (not just gateb_audit.py's top-20) filtered to rows whose
failing fields include 'cogs' — to verify Phase 2 resolved the additive-sum cases and to
confirm the known Gate B report_won=TOTAL structural mismatch (§3, plan doc) is exactly
what remains. Read-only (--no-commit), no DB writes.

Usage: python scripts/check_cogs_faila_2026-08-15.py
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
        corp_file=str(Path(__file__).resolve().parent / "cogs_phase2_19corps_2026-08-15.txt"),
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

    s = agg["status"]; g = agg["gate"]
    tot = sum(s.values())
    print(f"\n감사 {tot}행 — pass {s['pass']} / fail {s['fail']} / pending {s['pending']}")
    print(f"gate: pass {g['pass']} / fail_a {g['fail_a']} / fail_b {g['fail_b']} / pending {g['pending']}")

    cogs_rows = [r for r in agg["fail_rows"] if "cogs" in r[3]]
    print(f"\ntotal fail_rows={len(agg['fail_rows'])}")
    print(f"cogs-field fail rows = {len(cogs_rows)}")
    for r in cogs_rows:
        print(f"  {r}")

    other_rows = [r for r in agg["fail_rows"] if "cogs" not in r[3]]
    print(f"\nother-field fail rows (non-cogs, should be unrelated to Phase 2) = {len(other_rows)}")
    for r in other_rows:
        print(f"  {r}")


if __name__ == "__main__":
    main()
