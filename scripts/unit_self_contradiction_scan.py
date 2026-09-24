"""R169 — scan for self-contradictory unit declarations and confirm them per section.

Rule and evidence: `fin2/audit/unit_self_contradiction.py` docstring, docs/PARSING_RULES.md R169.

Usage:
  python scripts/unit_self_contradiction_scan.py --era-min 2015 --out docs/qa/r169_scan.jsonl
  python scripts/unit_self_contradiction_scan.py --rcepts 20230322000822 --apply
--apply merges confirmed sections into fin2/extract/data/unit_self_contradiction_overrides.json.
Reload the affected filings afterwards (`vq.py batch add-targets` + `batch reload`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from collector.db import get_session
from fin2.audit.unit_self_contradiction import merge_confirmed, scan_rcept, suspect_rcepts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcepts", help="comma-separated rcept_no (default: DB suspects)")
    ap.add_argument("--era-min", type=int, default=2015)
    ap.add_argument("--out", help="JSONL report path")
    ap.add_argument("--apply", action="store_true", help="merge confirmed into the data file")
    args = ap.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    with get_session() as s:
        suspects = set(suspect_rcepts(s, args.era_min))
        targets = args.rcepts.split(",") if args.rcepts else sorted(suspects)
        suspects |= set(targets)
        results = []
        for i, rc in enumerate(targets, 1):
            try:
                rows = scan_rcept(s, rc, suspects)
            except Exception as e:  # noqa: BLE001
                rows = [{"rcept": rc, "decision": f"error:{type(e).__name__}:{e}"[:200]}]
            results.extend(rows)
            for r in rows:
                print(json.dumps(r, ensure_ascii=False), flush=True)
            if i % 10 == 0:
                print(f"# {i}/{len(targets)}", file=sys.stderr, flush=True)

    if args.out:
        Path(args.out).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    conf = [r for r in results if r.get("decision", "").startswith("confirmed:")]
    print(f"# sections: {len(results)} confirmed: {len(conf)} "
          f"rcepts confirmed: {len({r['rcept'] for r in conf})}", file=sys.stderr)
    if args.apply and conf:
        print(f"# data file now covers {merge_confirmed(conf)} rcepts", file=sys.stderr)


if __name__ == "__main__":
    main()
