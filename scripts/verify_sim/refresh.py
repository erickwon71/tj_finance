"""Recompute machine findings of a snapshot with the current machine_compare (mc8)."""
import json, sys
from pathlib import Path
sys.path.insert(0, "/Users/taejin/Project/tj_finance")
from collector.db import engine
from fin2.verification import machine_compare as mc, machine_pass
snap = Path(sys.argv[1])
with engine.connect() as conn:
    for dj in sorted(snap.glob("*/detail.json")):
        s = json.loads(dj.read_text())
        for f in s["detail"]["filings"]:
            if f.get("machine_verdict") in ("mismatch", "clean") and f.get("machine_current"):
                path = machine_pass._source_path(conn, f["rcept_no"])
                res = mc.compare_filing(conn, f["rcept_no"], path)
                old = (f["machine_verdict"], len(f.get("machine_findings") or []))
                f["machine_verdict"] = res.verdict
                f["machine_counts"] = dict(res.counts)
                f["machine_findings"] = res.findings
                f["machine_tool"] = mc.TOOL_VERSION
                print(dj.parent.name, f["rcept_no"], old, "->", res.verdict, len(res.findings))
        dj.write_text(json.dumps(s, ensure_ascii=False, default=str))
