"""Drill: characterize MISSING cases from layer3_label_norm_probe (READ-ONLY).

For bs.total_assets (every corp has it), find sampled filings where the probe
found no value, and classify why:
  NO_BS_ROWS    : report_lines has no BS col_index=0 rows for this key at all
                  (basis mismatch or filing not in layer2)
  HAS_ROWS_NOMAP: BS rows exist but none map to bs.total_assets
                  (catalog gap or financial-firm label)
Prints the raw labels present for a few HAS_ROWS_NOMAP cases so we can see what
the top-line looks like.
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
from parser.common.account_mapper import get_mapper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    mapper = get_mapper()
    kind = Counter()
    nomap_examples = []

    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type
            FROM std_financials_v2
            WHERE fiscal_year >= 2015 AND fiscal_period='FY'
              AND version=1 AND NOT is_stub AND NOT is_discrete
              AND total_assets IS NOT NULL
        """)).fetchall()
        rnd = random.Random(args.seed)
        rnd.shuffle(rows)
        keys = rows[:args.sample]

        for corp, fy, period, stmt_type in keys:
            bs_rows = s.execute(text("""
                SELECT label_raw, value_won FROM report_lines
                WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
                  AND basis=:b AND statement='BS' AND col_index=0 AND value_won IS NOT NULL
            """), {"c": corp, "y": fy, "p": period, "b": stmt_type}).fetchall()

            mapped = False
            for label_raw, _ in bs_rows:
                r = mapper.map(label_raw, fs_section="bs")
                if r.account_code == "bs.total_assets" and r.confidence >= 0.88:
                    mapped = True
                    break
            if mapped:
                kind["MAPPED_OK"] += 1
            elif not bs_rows:
                kind["NO_BS_ROWS"] += 1
            else:
                kind["HAS_ROWS_NOMAP"] += 1
                if len(nomap_examples) < 8:
                    labels = [lr for lr, _ in bs_rows]
                    nomap_examples.append((corp, fy, stmt_type, labels[:12]))

    print("bs.total_assets MISSING classification:")
    for k, v in kind.most_common():
        print(f"  {k:<16}{v:>5}")
    print("\nHAS_ROWS_NOMAP raw labels (first BS rows — why no total_assets?):")
    for corp, fy, t, labels in nomap_examples:
        print(f"\n  {corp} {fy} {t}:")
        for lr in labels:
            print(f"      {lr!r}")


if __name__ == "__main__":
    main()
