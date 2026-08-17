"""Read-only profiler for gateb_audit.audit_corp — Phase 0 of the Gate B performance track (③).

Why this exists: the "corp 1개 36분+" figure (docs/PARSING_RULES.md R31 note, corp 00101044)
is NOT explained by the obvious suspects. Measured 2026-08-17:

  - face reader, one 11.4MB filing end-to-end   0.78s  (_parse_xml_file 0.63s of it)
  - NAS(SMB) cold read                          50 MB/s (SD mirror 93 MB/s — only ~2x)
  - corp 00101044 total source bytes            131 MB across 91 filings (avg 1.44MB)

  => I/O + parsing for the whole corp should be ~1 minute, not 36. The bottleneck is
     somewhere else and must be MEASURED before the ③ design is written (R9 / 짐작 금지).

Runs the real audit path with --no-commit (writes nothing) under cProfile and prints the
top cumulative-time functions.

usage (long-running — run it yourself, see feedback-long-running-commands):
  python scripts/profile_gateb_audit_2026-08-17.py --corp 00101044
  python scripts/profile_gateb_audit_2026-08-17.py --corp 00101044 --no-line-audit
"""
from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector.db import get_session          # noqa: E402
import gateb_audit                            # noqa: E402  (scripts/ on sys.path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp", default="00101044")
    ap.add_argument("--source", default="v3", choices=["v2", "v3"])
    ap.add_argument("--fy-min", type=int, default=2010)
    ap.add_argument("--no-line-audit", dest="line_audit", action="store_false",
                    help="Phase B 라인 대조를 빼고 측정 — 면표 대조 단독 비용 분리용")
    ap.add_argument("--top", type=int, default=35)
    ap.set_defaults(line_audit=True)
    a = ap.parse_args()

    args = SimpleNamespace(
        corp=a.corp, corp_file=None, corps=None, sample=None, seed=42,
        fy_min=a.fy_min, fy_max=2100, recheck=True, no_commit=True,   # ★ no_commit
        line_audit=a.line_audit, source=a.source,
    )
    agg = {"status": Counter(), "gate": Counter(), "fld_pass": 0, "fld_fail": 0,
           "fail_rows": [], "errors": 0}

    print(f"corp={a.corp} source={a.source} line_audit={a.line_audit} (no-commit)")
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    with get_session() as s:
        prof.enable()
        gateb_audit.audit_corp(s, a.corp, args, agg)
        prof.disable()
    wall = time.perf_counter() - t0

    print(f"\n── wall {wall:.1f}s · status={dict(agg['status'])} errors={agg['errors']}")
    buf = io.StringIO()
    pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(a.top)
    print(buf.getvalue())


if __name__ == "__main__":
    main()
