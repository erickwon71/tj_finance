"""Layer-3 correction backlog (user decision 2026-10-10: the verification campaign checks layer-2
faithfulness only; source arithmetic / suspected dropped parentheses are collected here and
corrected in layer 3 in one go).

Reads the latest machine check of every filing and lists its identity findings (sce_arith,
sce_identity, sign_omitted, bs_identity) that layer 3 does NOT already close (`l3_covered`).
Read-only.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/layer3_backlog.py <out.jsonl>        # one line per finding
Prints a summary per kind / fiscal year.
"""
import json
import os
import sys
from collections import Counter

import psycopg2

KINDS = ("sce_arith", "sce_identity", "sign_omitted", "bs_identity")
SQL = """
SELECT DISTINCT ON (mc.rcept_no) mc.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
       mc.tool_version, mc.findings
FROM verification.machine_checks mc JOIN filings f USING (rcept_no)
ORDER BY mc.rcept_no, mc.checked_at DESC"""


def main():
    out_path = sys.argv[1]
    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor(name="backlog")
    cur.itersize = 2000
    cur.execute(SQL)
    by_kind, by_year, covered, n_filings = Counter(), Counter(), Counter(), set()
    with open(out_path, "w") as fo:
        for rcept, corp, fy, fp, tool, findings in cur:
            for f in findings or []:
                kind = f.get("kind")
                if kind not in KINDS:
                    continue
                if f.get("l3_covered"):
                    covered[kind] += 1
                    continue
                by_kind[kind] += 1
                by_year[fy] += 1
                n_filings.add(rcept)
                fo.write(json.dumps({"rcept_no": rcept, "corp_code": corp, "fiscal_year": fy,
                                     "fiscal_period": fp, "tool": tool, **f},
                                    ensure_ascii=False, default=str) + "\n")
    print("backlog (not closed by layer 3):", dict(by_kind), "filings", len(n_filings))
    print("already closed by layer 3:", dict(covered))
    print("by fiscal year:", dict(sorted(by_year.items())))


if __name__ == "__main__":
    main()
