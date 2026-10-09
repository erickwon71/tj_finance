"""Compare simulated verifier runs: per slot, do all runs produce the same outcome?

Usage: compare.py <round> [run_dir ...]   (default: every <model>_<rep> dir under runs/<round>)
Outcome of a run = per filing (pass|issues|skip|none) + set of registered issues keyed by
(rcept, basis, statement, normalized account label, normalized column label, error_type)."""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

S = Path(os.environ.get("SIM_HOME", "/Users/taejin/Project/tj_finance/logs/verify_sim"))
rnd = sys.argv[1]
manifest = json.loads((Path(os.environ.get("SNAPDIR", S / "snap")) / "manifest.json").read_text())
runs = sys.argv[2:] or sorted(p.name for p in (S / "runs" / rnd).iterdir() if p.is_dir())


def norm(s):
    s = str(s or "")
    s = re.sub(r"\s+", "", s)
    s = s.replace(">", "")
    s = re.sub(r"\[(abstract|lineitems|member)\]", "", s, flags=re.I)
    s = re.sub(r"\(주석?\d+[^)]*\)|주\d+", "", s)
    s = re.sub(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.|\d+\.|\(\d+\)|[가-하]\.)", "", s)
    return s


def outcome(run, i):
    d = S / "runs" / rnd / run / str(i)
    cj = d / "claude.json"
    if not cj.exists() or not cj.stat().st_size:
        return None
    meta = {}
    for line in cj.read_text().splitlines()[::-1]:
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(x, dict) and x.get("type") == "result":
            meta = x
            break
    acts = [json.loads(x) for x in (d / "actions.jsonl").read_text().splitlines()] if (d / "actions.jsonl").exists() else []
    fil = {}
    issues = set()
    for a in acts:
        if a["act"] == "pass":
            fil[a["rcept"]] = "pass"
        elif a["act"] == "skip":
            fil[a["rcept"]] = "skip"
        elif a["act"] == "issue":
            it = a["item"]
            fil[a["rcept"]] = "issues"
            issues.add((a["rcept"][-6:], it.get("basis", "")[:3], it.get("statement"), norm(it.get("account_label")),
                        norm(it.get("column_label")), it.get("error_type")))
        elif a["act"] in ("close", "reopen", "withdraw"):
            issues.add(("transition", a["act"], a["issue_id"]))
    done = any(a["act"] == "done" for a in acts)
    return {"fil": fil, "issues": issues, "done": done, "turns": meta.get("num_turns"),
            "cost": meta.get("total_cost_usd") or 0, "sub": meta.get("subtype")}


agree_slots, total, cost = 0, 0, Counter()
for i, m in enumerate(manifest):
    outs = {r: outcome(r, i) for r in runs}
    outs = {r: o for r, o in outs.items() if o}
    if not outs:
        continue
    total += 1
    sigs = {r: (tuple(sorted(o["fil"].items())), frozenset(o["issues"])) for r, o in outs.items()}
    same = len(set(sigs.values())) == 1
    agree_slots += same
    for r, o in outs.items():
        cost[r.split("_")[0]] += o["cost"]
    print(f"\n[{i}] {m['stratum']} {m['slot']}  {'SAME' if same else 'DIFF'}")
    allk = set().union(*(o["issues"] for o in outs.values()))
    for r, o in outs.items():
        print(f"   {r:10s} fil={dict(o['fil'])} issues={len(o['issues'])} done={o['done']} turns={o['turns']} ${o['cost']:.2f} {o['sub']}")
    if not same:
        for k in sorted(allk, key=str):
            who = [r for r, o in outs.items() if k in o["issues"]]
            if len(who) != len(outs):
                print(f"      {'+'.join(who):30s} {k}")
print(f"\nSLOTS identical across {runs}: {agree_slots}/{total}   cost: {dict(cost)}")
