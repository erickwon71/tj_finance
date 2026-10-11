"""One-time backfill (2026-10-11): passed filings whose byte-identical scope twin (earlier filing
of the same slot) still has unresolved issues — carry those issues onto them and take the pass
back, as `ops.pass_filing` now does (`ops._carry_twin_issues`).

Usage (cwd = repo root, DATABASE_URL set): python scripts/verification_twin_carry_backfill.py [--apply]
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from sqlalchemy import text  # noqa: E402

from fin2.verification import ops  # noqa: E402

_PAIRS_SQL = """
WITH p AS (SELECT pf.*, fl.scope_hashes FROM verification.progress_filings pf
           JOIN verification.filing_loads fl USING (rcept_no) WHERE pf.status = 'passed')
SELECT DISTINCT p.rcept_no FROM p
JOIN verification.progress_filings e
  ON (e.corp_code, e.fiscal_year, e.fiscal_period) = (p.corp_code, p.fiscal_year, p.fiscal_period)
 AND e.seq_in_slot < p.seq_in_slot
JOIN verification.filing_loads el ON el.rcept_no = e.rcept_no
JOIN verification.issues i ON i.rcept_no = e.rcept_no AND i.status <> 'closed'
WHERE p.scope_hashes ->> ((CASE WHEN i.basis = 'separate' THEN 'sep' ELSE 'con' END) || '-' ||
                         lower(CASE WHEN i.statement = 'CIS' THEN 'IS' ELSE i.statement END))
    = el.scope_hashes ->> ((CASE WHEN i.basis = 'separate' THEN 'sep' ELSE 'con' END) || '-' ||
                          lower(CASE WHEN i.statement = 'CIS' THEN 'IS' ELSE i.statement END))
ORDER BY 1"""


def main(apply: bool) -> None:
    with ops._Tx(evidence="twin carry backfill (2026-10-11)") as conn:
        rcepts = [r[0] for r in conn.execute(text(_PAIRS_SQL))]
        out = []
        for rc in rcepts:
            f = ops._filing(conn, rc)
            carried = ops._carry_twin_issues(conn, f)
            conn.execute(text("""
                UPDATE verification.progress_filings
                   SET status = 'has_issues', note = left(coalesce(note, '') ||
                       ' · [2026-10-11] 쌍둥이 미해결 이슈 승계로 pass 취소', 2000), updated_at = now()
                 WHERE rcept_no = :r"""), {"r": rc})
            conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"),
                         {"c": f["corp_code"], "y": f["fiscal_year"], "p": f["fiscal_period"]})
            out.append({"rcept": rc, "carried": len(carried),
                        "from": sorted({c["from_rcept"] for c in carried})})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"{len(out)} filings, {sum(o['carried'] for o in out)} issues carried")
        if not apply:
            raise SystemExit("dry run — rolled back (use --apply)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
