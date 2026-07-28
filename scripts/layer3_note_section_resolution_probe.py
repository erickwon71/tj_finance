"""
Layer 2 note `section_path` resolution probe (READ-ONLY).

Follow-up to layer3_note_da_period_probe.py --diagnose, which showed that ~50%
of corps expose D&A only under the generic document title '연결재무제표 주석'
rather than a numbered note section ('29. 비용의 성격별 분류'). This checks
whether that is a real Layer 2 section-detection failure (the running-header fix
in 9541a66 not landing for those filings) or simply how those reports are built.

For each sampled corp it reports the distribution of distinct `section_path`
values across ALL note lines, flagging filings whose section_path never resolves
past the document-level title.

Writes nothing to the DB.

Usage
-----
    python scripts/layer3_note_section_resolution_probe.py --corps 120
    python scripts/layer3_note_section_resolution_probe.py --show 00155948
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# Document-level titles that mean "section not resolved to a numbered note".
_GENERIC = re.compile(r"^\s*(연결)?재무제표\s*(에\s*대한\s*)?주석\s*$")
# A resolved note title normally starts with a note number: '29. ...'
_NUMBERED = re.compile(r"^\s*\d+\s*[.．]")

SECTIONS_SQL = text(
    """
    SELECT rcept_no, section_path, count(*) AS n
    FROM note_lines
    WHERE corp_code = :corp
      AND report_fiscal_year = :year
      AND report_fiscal_period = 'FY'
      AND basis = :basis
      AND statement = 'note'
    GROUP BY rcept_no, section_path
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=120)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--seed", type=int, default=20260727)
    ap.add_argument("--show", help="dump section_path list for one corp_code")
    args = ap.parse_args()

    with get_session() as session:
        if args.show:
            rows = session.execute(
                SECTIONS_SQL,
                {"corp": args.show, "year": args.year, "basis": args.basis},
            ).fetchall()
            latest = max((r.rcept_no for r in rows), default=None)
            print(f"corp={args.show} FY{args.year} {args.basis} rcept={latest}")
            for r in sorted(
                (r for r in rows if r.rcept_no == latest), key=lambda r: -r.n
            ):
                print(f"  {r.n:>6}  {(r.section_path or '<NULL>')[:90]}")
            return 0

        corps = [
            r[0]
            for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        verdicts: Counter[str] = Counter()
        unresolved_examples: list[str] = []

        for corp in corps:
            rows = session.execute(
                SECTIONS_SQL, {"corp": corp, "year": args.year, "basis": args.basis}
            ).fetchall()
            if not rows:
                verdicts["NO_NOTES"] += 1
                continue
            latest = max(r.rcept_no for r in rows)
            paths = [
                (r.section_path or "") for r in rows if r.rcept_no == latest
            ]
            # The real signal is not "does the path start with a number" (the
            # collapsed case is '3. 연결재무제표 주석' — a numbered *report*
            # section, not a note heading). It is whether the notes got split
            # into per-note headings at all.
            generic_only = all(
                _GENERIC.match(re.sub(r"^\s*\d+\s*[.．]\s*", "", p)) for p in paths
            )
            if len(paths) <= 1 or generic_only:
                verdicts["COLLAPSED"] += 1
                if len(unresolved_examples) < 10:
                    unresolved_examples.append(
                        f"{corp} rcept={latest} distinct_paths={len(paths)} "
                        f"sample={paths[0][:60]!r}"
                    )
            elif len(paths) < 5:
                verdicts["PARTIAL(<5)"] += 1
            else:
                verdicts["RESOLVED"] += 1

        total = sum(verdicts.values())
        print(f"=== note section_path resolution · FY{args.year} · {args.basis} "
              f"(n={total}) ===")
        for k, v in verdicts.most_common():
            print(f"  {k:<24} {v:>5}  {v / total * 100:5.1f}%")
        if unresolved_examples:
            print("\n--- unresolved examples ---")
            for line in unresolved_examples:
                print(f"  {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
