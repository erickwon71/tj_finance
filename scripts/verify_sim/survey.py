"""Survey model-ready pending slots: finding-kind mix per slot (read-only)."""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/Users/taejin/Project/tj_finance")
sys.path.insert(0, str(REPO))
from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402
from fin2.verification import ops  # noqa: E402

SQL = f"""
SELECT p.corp_code, p.fiscal_year, p.fiscal_period, p.status, p.corp_rank,
       count(pf.*) AS n_filings,
       array_agg(DISTINCT mc.verdict) AS verdicts,
       bool_or(mc.audit) AS any_audit,
       jsonb_agg(mc.counts) AS counts
FROM verification.progress p
JOIN verification.progress_filings pf USING (corp_code, fiscal_year, fiscal_period)
LEFT JOIN verification.machine_checks mc ON mc.rcept_no = pf.rcept_no
WHERE p.status IN ('pending','has_issues') AND pf.status = 'pending'
  AND {ops._model_ready_sql()}
GROUP BY 1,2,3,4,5
"""
with engine.connect() as conn:
    rows = [dict(r) for r in conn.execute(text(SQL)).mappings()]
print("model-ready slots:", len(rows))
kinds = Counter()
out = []
for r in rows:
    ks = Counter()
    for c in r["counts"] or []:
        for k, v in (c or {}).items():
            ks[k] += v
    r["kinds"] = dict(ks)
    for k in ks:
        kinds[k] += 1
    out.append({k: (str(v) if k == "counts" else v) for k, v in r.items() if k != "counts"})
print("slots having kind:", dict(kinds))
print("status:", Counter(r["status"] for r in rows), "audit:", sum(bool(r["any_audit"]) for r in rows))
print("verdicts:", Counter(tuple(sorted(x for x in r["verdicts"] if x)) for r in rows))
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, default=str, indent=0))
