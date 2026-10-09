"""Pick a stratified set of model-ready slots and freeze everything the verifier sees.

Usage: snapshot.py <cands.json> <snap_dir> [n_per_stratum]
Writes <snap_dir>/<slot>/detail.json, recheck.json, csv/<rcept>.csv and <snap_dir>/manifest.json.
Read-only on the DB (slot_detail/recheck_list/write_review_csvs only read)."""
import json
import random
import shutil
import sys
from pathlib import Path

REPO = Path("/Users/taejin/Project/tj_finance")
sys.path.insert(0, str(REPO))
from fin2.verification import ops  # noqa: E402
from fin2.verification.ops import Slot  # noqa: E402

cands = json.loads(Path(sys.argv[1]).read_text())
snap = Path(sys.argv[2]).resolve()
snap.mkdir(parents=True, exist_ok=True)
rng = random.Random(20261009)

# stratum -> predicate on the candidate's kind counts; one filing preferred to keep runs short
STRATA = [
    ("value_small", lambda k, c: 0 < k.get("value", 0) < 10 and len(k) <= 4),
    ("value_bulk", lambda k, c: k.get("value", 0) >= 10),
    ("sce_identity", lambda k, c: k.get("sce_identity", 0) > 0),
    ("sce_arith", lambda k, c: k.get("sce_arith", 0) > 0 and not k.get("value")),
    ("sign_omitted", lambda k, c: k.get("sign_omitted", 0) > 0),
    ("bs_identity", lambda k, c: k.get("bs_identity", 0) > 0),
    ("missing_row", lambda k, c: 0 < k.get("missing_row", 0)),
    ("extra_row", lambda k, c: 0 < k.get("extra_row", 0)),
    ("unmatched_table", lambda k, c: k.get("unmatched_table", 0) > 0),
    ("no_table", lambda k, c: k.get("no_table", 0) > 0),
    ("uncovered_cell", lambda k, c: k.get("uncovered_cell", 0) > 0),
    ("zero_row_only", lambda k, c: k.get("zero_row", 0) > 0 and not (set(k) - {"zero_row", "rows", "cells", "prior_only", "sign_restored"})),
    ("audit_clean", lambda k, c: c["any_audit"] and c["verdicts"] == ["clean"]),
    ("no_source", lambda k, c: "no_source" in c["verdicts"]),
]
n_per = int(sys.argv[3]) if len(sys.argv) > 3 else 1
picked, used = [], set()
for name, pred in STRATA:
    pool = [c for c in cands if pred(c["kinds"], c) and c["n_filings"] == 1]
    if not pool:
        pool = [c for c in cands if pred(c["kinds"], c)]
    rng.shuffle(pool)
    n = 0
    for c in pool:
        s = f'{c["corp_code"]}:{c["fiscal_year"]}:{c["fiscal_period"]}'
        if s in used:
            continue
        used.add(s)
        picked.append({"stratum": name, "slot": s, "kinds": c["kinds"], "status": c["status"]})
        n += 1
        if n >= n_per:
            break

for p in picked:
    slot = Slot.parse(p["slot"])
    d = ops.slot_detail(slot)
    if d["slot"].get("status") == "in_progress":
        print("skip in_progress", p["slot"])
        p["skip"] = True
        continue
    sd = snap / p["slot"].replace(":", "_")
    (sd / "csv").mkdir(parents=True, exist_ok=True)
    csvs = ops.write_review_csvs(slot, d)
    local = {}
    for r, path in csvs.items():
        dst = sd / "csv" / Path(path).name
        shutil.copy(path, dst)
        local[r] = str(dst)
    rc = ops.recheck_list(slot)
    # the verifier must see the slot as it is when claimed
    d["slot"]["status"] = "in_progress"
    d["slot"]["claimed_by"] = "camp_run"
    d["slot"]["lease_until"] = "(sim)"
    (sd / "detail.json").write_text(json.dumps({"detail": d, "csvs": local}, ensure_ascii=False, default=str))
    (sd / "recheck.json").write_text(json.dumps(rc, ensure_ascii=False, default=str))
    print(p["stratum"], p["slot"], p["kinds"], "filings", len(d["filings"]), "fixed", len(rc))
picked = [p for p in picked if not p.get("skip")]
(snap / "manifest.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1))
print("picked", len(picked))
