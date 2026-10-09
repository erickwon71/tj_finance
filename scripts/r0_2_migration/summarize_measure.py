"""Summarize measure_as_printed.py output: cells per rule and statement, filings to reload, drift.

Usage: python scripts/r0_2_migration/summarize_measure.py <measure.jsonl> <reload_targets.txt> <drift.txt>
"""
import json
import sys
from collections import Counter


def main():
    src, targets_path, drift_path = sys.argv[1:4]
    seen = {}
    for line in open(src):
        d = json.loads(line)
        seen[d["rcept"]] = d                      # last record wins (resumed runs)
    status = Counter()
    cells = Counter()                             # (rule, statement) -> cells
    filings = Counter()                           # rule -> filings
    kinds = Counter()
    targets, drift = [], []
    unattr = Counter()
    for rc, d in seen.items():
        st = d["status"] if not d["status"].startswith("err") else "err"
        status[st] += 1
        if d["status"] != "ok":
            continue
        changed = bool(d["steps"]) or bool(d["unattributed"])
        for rule, ds in d["steps"].items():
            filings[rule] += 1
            for k, a, b in ds:
                cells[(rule, k[0])] += 1
                kinds["fill" if a == "absent" else "drop" if b == "absent" else "value"] += 1
        for k, a, b in d["unattributed"]:
            unattr[(d["ftype"], k[0])] += 1
        if d.get("n_drift"):
            drift.append(rc)
        elif changed:
            targets.append(rc)
    open(targets_path, "w").write("\n".join(sorted(targets)) + "\n")
    open(drift_path, "w").write("\n".join(sorted(drift)) + "\n")
    print("filings with a record:", len(seen), dict(status))
    print("reload targets (rules change cells, DB = rules-on):", len(targets))
    print("drift filings (DB != current code, not reloaded):", len(drift))
    print("\nrule | statement | cells")
    for (rule, stmt), n in sorted(cells.items(), key=lambda x: -x[1]):
        print(f"{rule} | {stmt} | {n}")
    print("\nrule | filings")
    for rule, n in filings.most_common():
        print(f"{rule} | {n}")
    print("\nchange kinds:", dict(kinds))
    print("unattributed (ftype, statement):", dict(unattr))


if __name__ == "__main__":
    main()
