"""Probe (read-only) — classify the CURRENT residual fail_a rows for trade_payables and
revenue after R16 (docs/PARSING_RULES.md), continuing the fail_a triage
(docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md).

Same technique as that triage doc's §2 code scan (no guessing): for each fail_a row,
resolve the canonical filing (rcept_no) for its statement, pull report_lines for that
(rcept, basis, statement, col_index=0), and check whether report_won already exists
verbatim as SOME OTHER row's value_won — classify by that row's node_role. For rows
where no exact match exists, bucket by db_won/report_won ratio (scale mismatches show
up as a suspiciously round ratio like ~1000).

Read-only: no DB writes, no source changes.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from fin2.layer3.combine import select_canonical_rcepts

STATEMENT_OF_FIELD = {
    "trade_payables": "BS", "revenue": "IS",
}
CANON_OF_FIELD = {
    "trade_payables": "bs.trade_payables", "revenue": "is.revenue",
}


def classify(session, field: str):
    stmt = STATEMENT_OF_FIELD[field]
    rows = session.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type, fail_detail
        FROM face_audit
        WHERE source_version='v3' AND gate_status='fail_a'
          AND fail_fields ? :f
    """), {"f": field}).fetchall()

    exact_match: list = []       # report_won found verbatim elsewhere in report_lines
    scale_1000: list = []        # db_won == report_won * 1000 (unit scale bug)
    scale_other: list = []       # some other suspiciously round ratio
    unmatched: list = []         # no exact match, no round ratio
    node_role_counts = Counter()

    for corp, fy, period, basis, detail in rows:
        d = next((x for x in detail if x.get("field") == field), None)
        if d is None:
            continue
        report_won = d.get("report_won")
        db_won = d.get("db_won")
        if report_won is None or db_won is None:
            continue
        rcepts = select_canonical_rcepts(session, corp, fy, period, statements=(stmt,))
        rcept = rcepts.get(stmt)
        if not rcept:
            unmatched.append((corp, fy, period, "NO_RCEPT"))
            continue
        lines = session.execute(text("""
            SELECT label_raw, value_won, node_role, section_path
            FROM report_lines
            WHERE rcept_no=:r AND basis=:b AND statement=:s AND col_index=0
              AND value_won IS NOT NULL AND header_hint IS NULL
        """), {"r": rcept, "b": basis, "s": stmt}).fetchall()

        hit = [r for r in lines if r[1] == report_won]
        if hit:
            roles = {r[2] for r in hit}
            node_role_counts[",".join(sorted(x or "NULL" for x in roles))] += 1
            exact_match.append((corp, fy, period, basis, report_won, db_won,
                                [(r[0], r[2]) for r in hit]))
            continue

        ratio = db_won / report_won if report_won else None
        if ratio is not None and abs(ratio - 1000) < 0.01:
            scale_1000.append((corp, fy, period, basis, report_won, db_won))
        elif ratio is not None and abs(round(ratio) - ratio) < 1e-6 and ratio not in (0, 1):
            scale_other.append((corp, fy, period, basis, report_won, db_won, ratio))
        else:
            unmatched.append((corp, fy, period, basis, report_won, db_won,
                              [(r[0], r[1], r[2]) for r in lines]))

    print(f"\n=== {field} === total={len(rows)}")
    print(f"exact_match(report_won already in report_lines)={len(exact_match)}")
    for k, v in node_role_counts.most_common():
        print(f"  node_role of matching row(s)={k}: {v}")
    print(f"scale_1000x={len(scale_1000)}")
    print(f"scale_other_round_ratio={len(scale_other)}")
    print(f"unmatched(no exact, no round ratio)={len(unmatched)}")
    return {"exact_match": exact_match, "scale_1000": scale_1000,
            "scale_other": scale_other, "unmatched": unmatched}


def main():
    init_db()
    with get_session() as s:
        tp = classify(s, "trade_payables")
        rv = classify(s, "revenue")

    print("\n--- trade_payables scale_1000x sample (corp/fy/period/basis/report_won/db_won) ---")
    for row in tp["scale_1000"][:10]:
        print(row)
    print("\n--- trade_payables scale_other sample ---")
    for row in tp["scale_other"][:10]:
        print(row)
    print("\n--- trade_payables unmatched corp distribution ---")
    corp_ct = Counter(r[0] for r in tp["unmatched"])
    for c, n in corp_ct.most_common(20):
        print(c, n)

    print("\n--- revenue scale_1000x sample ---")
    for row in rv["scale_1000"][:10]:
        print(row)
    print("\n--- revenue unmatched corp distribution ---")
    corp_ct = Counter(r[0] for r in rv["unmatched"])
    for c, n in corp_ct.most_common(20):
        print(c, n)


if __name__ == "__main__":
    main()
