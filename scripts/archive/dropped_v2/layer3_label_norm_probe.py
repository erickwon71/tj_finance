"""
Layer 3 label-normalization probe (READ-ONLY).

Goal (handoff 2026-07-22, Option A): verify at the *metric* level whether the
2015+ range is really standardized enough to build Layer 3 on top of Layer 2
(report_lines). We do NOT build Layer 3 here — we only measure whether the
existing label catalog (account_maps via parser.common.account_mapper) can
reproduce std_financials_v2 values directly from report_lines.label_raw.

Method
------
1. Sample N (corp, fiscal_year, fiscal_period, statement_type) rows from
   std_financials_v2 (the comparison target; small table, has PK) for FY,
   year >= 2015.
2. For each sample, pull the matching report_lines (col_index=0 = current
   year) for the relevant statement (IS / BS), run AccountMapper.map() on each
   label_raw, and collect candidate values per canonical metric.
3. Compare the probe-extracted value to std_v2's stored column.

Decision per metric per filing:
  - MISSING  : probe found no value mapping to this canonical
  - UNIQUE   : probe found exactly one distinct value
        -> MATCH if it equals std_v2's value (exact, won units)
        -> DIFF  otherwise
  - CONFLICT : probe found multiple distinct candidate values (ambiguous)

High MATCH% + low CONFLICT% => 2015+ standardization assumption holds; proceed
with Layer 3 label normalization. Otherwise return to layer3_design §4.

This script writes nothing to the DB.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.common.account_mapper import get_mapper


# canonical metric -> (std_v2 column, statement, fs_section)
TARGETS = [
    ("is.revenue",           "revenue",           "IS", "is"),
    ("is.operating_income",  "operating_income",  "IS", "is"),
    ("is.net_income",        "net_income",        "IS", "is"),
    ("bs.total_assets",      "total_assets",      "BS", "bs"),
    ("bs.total_equity",      "total_equity",      "BS", "bs"),
    ("bs.retained_earnings", "retained_earnings", "BS", "bs"),
]


def sample_std_keys(session, n: int, period: str, seed: int):
    """Pick N random std_v2 keys (FY, year>=2015) that have at least one target
    column populated, so the comparison is meaningful."""
    cols_not_null = " OR ".join(f"{c[1]} IS NOT NULL" for c in TARGETS)
    rows = session.execute(text(f"""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type
        FROM std_financials_v2
        WHERE fiscal_year >= 2015
          AND fiscal_period = :period
          AND version = 1 AND NOT is_stub AND NOT is_discrete
          AND ({cols_not_null})
    """), {"period": period}).fetchall()
    rnd = random.Random(seed)
    rnd.shuffle(rows)
    return rows[:n]


def std_values(session, corp, fy, period, stmt_type):
    cols = ", ".join(c[1] for c in TARGETS)
    row = session.execute(text(f"""
        SELECT {cols} FROM std_financials_v2
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
          AND statement_type=:t AND version=1 AND NOT is_stub AND NOT is_discrete
        LIMIT 1
    """), {"c": corp, "y": fy, "p": period, "t": stmt_type}).fetchone()
    if not row:
        return {}
    return {c[1]: row[i] for i, c in enumerate(TARGETS)}


def probe_report_lines(session, mapper, corp, fy, period, basis, statement, fs_section):
    """Return {canonical: set(distinct values)} for current-year (col_index=0)
    lines of one statement, plus a stage Counter."""
    rows = session.execute(text("""
        SELECT label_raw, value_won, node_role
        FROM report_lines
        WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
          AND basis=:b AND statement=:s AND col_index=0 AND value_won IS NOT NULL
    """), {"c": corp, "y": fy, "p": period, "b": basis, "s": statement}).fetchall()

    cand: dict[str, set] = defaultdict(set)
    stages: Counter = Counter()
    for label_raw, value_won, node_role in rows:
        res = mapper.map(label_raw, fs_section=fs_section)
        stages[res.stage] += 1
        if res.confidence >= 0.88 and not res.account_code.startswith("unknown."):
            cand[res.account_code].add(int(value_won))
    return cand, stages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=200, help="filings to sample")
    ap.add_argument("--period", default="FY", help="fiscal_period (FY/H1/Q1/Q3)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    mapper = get_mapper()
    # per-metric tallies
    stat = {c[0]: Counter() for c in TARGETS}   # canonical -> Counter(MATCH/DIFF/CONFLICT/MISSING/NO_STD)
    stage_total: Counter = Counter()
    diff_examples: dict[str, list] = defaultdict(list)

    with get_session() as s:
        keys = sample_std_keys(s, args.sample, args.period, args.seed)
        print(f"sampled {len(keys)} std_v2 filings ({args.period}, year>=2015)\n")

        # group probe by statement to reduce queries
        for corp, fy, period, stmt_type in keys:
            svals = std_values(s, corp, fy, period, stmt_type)
            # probe both statements once per filing
            probe_by_stmt = {}
            for statement, fs_section in (("IS", "is"), ("BS", "bs")):
                cand, stages = probe_report_lines(
                    s, mapper, corp, fy, period, stmt_type, statement, fs_section)
                probe_by_stmt[statement] = cand
                stage_total.update(stages)

            for canonical, std_col, statement, fs_section in TARGETS:
                std_v = svals.get(std_col)
                if std_v is None:
                    stat[canonical]["NO_STD"] += 1
                    continue
                values = probe_by_stmt[statement].get(canonical, set())
                if not values:
                    stat[canonical]["MISSING"] += 1
                elif len(values) > 1:
                    stat[canonical]["CONFLICT"] += 1
                else:
                    pv = next(iter(values))
                    if pv == int(std_v):
                        stat[canonical]["MATCH"] += 1
                    else:
                        stat[canonical]["DIFF"] += 1
                        if len(diff_examples[canonical]) < 5:
                            diff_examples[canonical].append(
                                (corp, fy, stmt_type, pv, int(std_v)))

    # ── report ──────────────────────────────────────────────────────────
    print("=" * 78)
    print(f"{'metric':<22}{'N':>6}{'MATCH':>8}{'DIFF':>7}{'CONFL':>7}{'MISS':>7}{'match%':>9}")
    print("-" * 78)
    for canonical, *_ in TARGETS:
        c = stat[canonical]
        n = c["MATCH"] + c["DIFF"] + c["CONFLICT"] + c["MISSING"]
        pct = (100.0 * c["MATCH"] / n) if n else 0.0
        print(f"{canonical:<22}{n:>6}{c['MATCH']:>8}{c['DIFF']:>7}"
              f"{c['CONFLICT']:>7}{c['MISSING']:>7}{pct:>8.1f}%")
    print("=" * 78)
    print("mapping stage distribution (all mapped lines):")
    tot = sum(stage_total.values()) or 1
    for stg, cnt in stage_total.most_common():
        print(f"  {stg:<12}{cnt:>10}  ({100.0*cnt/tot:5.1f}%)")

    print("\nDIFF examples (probe vs std):")
    for canonical, exs in diff_examples.items():
        for corp, fy, t, pv, sv in exs:
            print(f"  {canonical:<22} {corp} {fy} {t}: probe={pv:,} std={sv:,}")


if __name__ == "__main__":
    main()
