"""L3-1b amendment-provenance probe (READ-ONLY).

Validates the 정본 policy's provenance requirement: after build_merged_lines
(원본 + 순차 델타 패치), cells patched by a 기재정정 carry amended=True / amended_by
/ amend_chain. This probe scans a sample and reports, for the 6 target metrics,
how many resolved values were amendment-affected, with a few chains shown.

Writes nothing.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.layer3.combine import build_merged_lines, _map_rows
from fin2.standardize.rules import DIRECT_MAP

TARGETS = ["is.revenue", "is.operating_income", "is.net_income",
           "bs.total_assets", "bs.total_equity", "bs.retained_earnings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=600)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args()

    amended_metric = Counter()
    total_metric = Counter()
    examples = []
    filings_with_amend = 0

    with get_session() as s:
        keys = s.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type
            FROM std_financials_v2
            WHERE fiscal_year>=2015 AND fiscal_period=:p
              AND version=1 AND NOT is_stub AND NOT is_discrete
        """), {"p": args.period}).fetchall()
        rnd = random.Random(args.seed)
        rnd.shuffle(keys)
        keys = keys[:args.sample]
        print(f"scanning {len(keys)} (corp,fy,basis) for amendment-affected metrics\n")

        for corp, fy, period, basis in keys:
            merged = build_merged_lines(s, corp, fy, period)
            if not merged:
                continue
            any_amend = any(c["amended"] for c in merged)
            if any_amend:
                filings_with_amend += 1
            cands = _map_rows(merged, period, basis, statements=("BS", "IS"))
            for canon in TARGETS:
                rows = cands.get(canon)
                if not rows:
                    continue
                total_metric[canon] += 1
                # a metric is amendment-affected if its (single) resolved candidate is amended
                amended_rows = [r for r in rows if r.get("amended")]
                if amended_rows:
                    amended_metric[canon] += 1
                    if len(examples) < args.examples:
                        r = amended_rows[0]
                        examples.append((canon, corp, fy, basis, r["value"],
                                         r.get("amended_by")))

    print(f"filings (corp,fy) with ANY amended cell: {filings_with_amend}/{len(keys)}\n")
    print(f"{'metric':<22}{'present':>9}{'amended':>9}")
    print("-" * 40)
    for canon in TARGETS:
        print(f"{canon:<22}{total_metric[canon]:>9}{amended_metric[canon]:>9}")

    print("\namendment-affected examples (metric value ← amended_by rcept):")
    for canon, corp, fy, basis, val, by in examples:
        print(f"  {canon:<22} {corp} {fy} {basis}: {val:,}  ←기재정정 {by}")


if __name__ == "__main__":
    main()
