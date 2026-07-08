"""
Partition the remaining (not-yet-swept) companies from expected_coverage.csv
into N roughly-equal shard files for parallel Tier-1 sweep workers.

Excludes corp_codes already fully covered by the pilot run
(docs/qa/results/sweep_all_companies.csv). Writes
docs/qa/results/shards/shard_1.csv ... shard_N.csv, each with the same
columns as expected_coverage.csv (corp_code,corp_name,stock_code,market,
fiscal_month,earliest_fy,latest_fy,distinct_fy_count) so they can be fed
straight into sweep_company_pages.py --input.
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_DIR = os.path.join(ROOT, "docs", "qa", "results")
SHARDS_DIR = os.path.join(RESULTS_DIR, "shards")
COVERAGE_CSV = os.path.join(RESULTS_DIR, "expected_coverage.csv")
PILOT_SWEEP_CSV = os.path.join(RESULTS_DIR, "sweep_all_companies.csv")

N_SHARDS = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def main():
    with open(COVERAGE_CSV, encoding="utf-8-sig") as f:
        all_rows = list(csv.DictReader(f))
    print(f"total companies in expected_coverage.csv: {len(all_rows)}")

    done_codes = set()
    if os.path.exists(PILOT_SWEEP_CSV):
        with open(PILOT_SWEEP_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                done_codes.add(row["corp_code"])
    print(f"already covered by pilot sweep: {len(done_codes)} distinct corp_codes")

    remaining = [r for r in all_rows if r["corp_code"] not in done_codes]
    print(f"remaining to shard: {len(remaining)}")

    os.makedirs(SHARDS_DIR, exist_ok=True)
    fieldnames = list(remaining[0].keys()) if remaining else [
        "corp_code", "corp_name", "stock_code", "market", "fiscal_month",
        "earliest_fy", "latest_fy", "distinct_fy_count",
    ]

    shard_sizes = []
    base = len(remaining) // N_SHARDS
    extra = len(remaining) % N_SHARDS
    idx = 0
    for i in range(N_SHARDS):
        size = base + (1 if i < extra else 0)  # spread remainder over first shards
        chunk = remaining[idx: idx + size]
        idx += size
        shard_path = os.path.join(SHARDS_DIR, f"shard_{i + 1}.csv")
        with open(shard_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in chunk:
                w.writerow(row)
        shard_sizes.append((shard_path, len(chunk)))

    assert idx == len(remaining), f"partition mismatch: {idx} != {len(remaining)}"

    print("\nshard files written:")
    for path, n in shard_sizes:
        print(f"  {path}: {n} companies")
    print(f"\ntotal partitioned: {sum(n for _, n in shard_sizes)} (should equal {len(remaining)})")


if __name__ == "__main__":
    main()
