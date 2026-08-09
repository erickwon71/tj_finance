"""
Verify the <P> note-heading fix in section_detector (READ-ONLY; parses raw XML).

Background
----------
~57.5% of corps had every note line collapsed under a single '3. 연결재무제표 주석'
because per-note headings live in plain <P> text, which
`assign_note_tables_with_titles` did not track. The fix adds a <P> branch guarded
by monotonically increasing note numbers.

This harness answers the two questions that matter:

  1. REGRESSION — for filings whose `section_path` already resolved under the old
     code, does the new code still produce the same note titles? The DB holds the
     old code's output, so it is the baseline. Any change here is a regression.

  2. RECOVERY  — for collapsed filings, how many distinct notes does the new code
     now resolve (was: 1)?

The table filter (`note_table_retained`, ≡ has data rows) is reused from the real extractor
(fin2/extract/report_lines.py) so the comparison matches what would actually be written.
F1/D4 (2026-07-31) removed the unit-declared requirement — a note table is kept whenever it
has at least one comma-amount data row; unit determination only affects value_won vs
value_raw per column, not table retention.

Writes nothing to the DB.

Usage
-----
    python scripts/layer2_note_heading_fix_verify.py --corps 60
    python scripts/layer2_note_heading_fix_verify.py --only 00540863 -v
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import note_table_retained
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    SEC_CONSOL_NOTE,
    SEC_SEP_NOTE,
    assign_note_tables_with_titles,
)

RAW_ROOT = Path("raw_report")

FILINGS_SQL = text(
    """
    SELECT corp_code, max(rcept_no) AS rcept_no
    FROM filings
    WHERE fiscal_year = :year AND fiscal_period = 'FY'
      AND report_type = 'annual' AND is_final
    GROUP BY corp_code
    """
)

DB_SECTIONS_SQL = text(
    """
    SELECT DISTINCT section_path
    FROM report_tables
    WHERE rcept_no = :rcept AND basis = :basis AND statement = 'note'
    """
)


def find_xml(corp: str, year: int, rcept: str) -> Optional[Path]:
    for market in ("KOSPI", "KOSDAQ"):
        hits = list(RAW_ROOT.glob(f"{market}/{corp}_*/annual/{year}/{rcept}.xml"))
        if hits:
            return hits[0]
    return None


def new_titles(root, sec_kind: str) -> list[str]:
    """Note titles the NEW code assigns, restricted to tables that get written."""
    out = []
    for table, note_title in assign_note_tables_with_titles(root).get(sec_kind, []):
        if not note_table_retained(table):
            continue
        out.append(note_title or "<none>")
    return out


def is_collapsed(paths: set[str]) -> bool:
    if len(paths) <= 1:
        return True
    return all(
        re.match(r"^\s*(?:\d+\s*[.．]\s*)?(?:연결)?재무제표\s*주석\s*$", p or "")
        for p in paths
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=60)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--seed", type=int, default=20260727)
    ap.add_argument("--only", help="single corp_code")
    ap.add_argument("--dump", action="store_true", help="print recovered titles in order")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    verdicts: Counter[str] = Counter()
    recovery: list[tuple[str, int, int]] = []
    regressions: list[str] = []
    gaps: list[tuple[str, int, int]] = []

    with get_session() as session:
        latest = {
            r.corp_code: r.rcept_no
            for r in session.execute(FILINGS_SQL, {"year": args.year}).fetchall()
        }
        corps = [args.only] if args.only else sorted(latest)
        if not args.only:
            random.Random(args.seed).shuffle(corps)
            corps = corps[: args.corps]

        for corp in corps:
            rcept = latest.get(corp)
            if not rcept:
                verdicts["NO_FILING"] += 1
                continue
            xml = find_xml(corp, args.year, rcept)
            if xml is None:
                verdicts["NO_XML"] += 1
                continue
            # Use the production parser (sanitize_dart_xml() + recover) so this harness
            # sees the same tree the real pipeline built the DB baseline from. A raw
            # etree.parse(recover=True) here diverges on filings with genuine markup
            # defects (unescaped '&', broken attr quoting) — recover-mode then drops
            # whole trailing sections, producing false REGRESSED verdicts (00121969,
            # 00133812 traced 2026-08-09; see docs/qa handoff for this session).
            root = _parse_xml_file(xml)
            if root is None:
                verdicts["PARSE_ERROR"] += 1
                continue

            for sec_kind, basis in (
                (SEC_CONSOL_NOTE, "consolidated"),
                (SEC_SEP_NOTE, "separate"),
            ):
                db_paths = {
                    r[0]
                    for r in session.execute(
                        DB_SECTIONS_SQL, {"rcept": rcept, "basis": basis}
                    ).fetchall()
                }
                if not db_paths:
                    continue
                titles = new_titles(root, sec_kind)
                if args.dump:
                    print(f"\n--- {corp}/{basis}: {len(titles)} tables ---")
                    seen: list[str] = []
                    for t in titles:
                        if not seen or seen[-1] != t:
                            seen.append(t)
                            print(f"    {t}")
                if not titles:
                    verdicts["NO_TABLES_NEW"] += 1
                    continue
                new_set = set(titles)

                if is_collapsed(db_paths):
                    verdicts["RECOVERED" if len(new_set) > 1 else "STILL_COLLAPSED"] += 1
                    recovery.append((f"{corp}/{basis}", len(db_paths), len(new_set)))
                    # Gap metric: note numbers should form a contiguous run. Any
                    # missing number is a heading we still fail to detect, whose
                    # tables therefore mis-inherit the previous note.
                    nums = sorted(
                        {
                            int(mm.group(1))
                            for t in new_set
                            if (mm := re.match(r"^\s*(\d{1,2})\s*[.．]", t))
                        }
                    )
                    if len(nums) >= 2:
                        span = nums[-1] - nums[0] + 1
                        gaps.append((f"{corp}/{basis}", span - len(nums), span))
                else:
                    # Baseline case: the old code already resolved this filing.
                    if new_set == db_paths:
                        verdicts["UNCHANGED"] += 1
                    elif db_paths <= new_set:
                        verdicts["SUPERSET(ok)"] += 1
                        if args.verbose:
                            print(f"  + {corp}/{basis} added {sorted(new_set - db_paths)[:3]}")
                    else:
                        verdicts["REGRESSED"] += 1
                        if len(regressions) < 10:
                            lost = sorted(db_paths - new_set)[:4]
                            regressions.append(f"{corp}/{basis} lost={lost}")

    print(f"=== verdicts (n={sum(verdicts.values())}) ===")
    for k, v in verdicts.most_common():
        print(f"  {k:<18} {v:>5}")

    if recovery:
        gains = [(n, o, w) for n, o, w in recovery if w > 1]
        print(f"\n=== recovery on collapsed filings (n={len(recovery)}) ===")
        if gains:
            avg = sum(w for _, _, w in gains) / len(gains)
            print(f"  now resolving >1 note: {len(gains)}/{len(recovery)}"
                  f" · avg distinct notes {avg:.1f}")
        for name, old, new in recovery[:12]:
            print(f"    {name:<22} {old} -> {new}")

    if gaps:
        missing = sum(g for _, g, _ in gaps)
        span = sum(s for _, _, s in gaps)
        perfect = sum(1 for _, g, _ in gaps if g == 0)
        print(f"\n=== note-number gaps on recovered filings (n={len(gaps)}) ===")
        print(f"  missing numbers: {missing}/{span} = {missing / span * 100:.1f}%")
        print(f"  gapless filings: {perfect}/{len(gaps)} = {perfect / len(gaps) * 100:.1f}%")
        worst = sorted(gaps, key=lambda t: -t[1])[:5]
        for name, g, s in worst:
            print(f"    {name:<22} missing {g} of span {s}")

    if regressions:
        print("\n--- REGRESSIONS ---")
        for r in regressions:
            print(f"  {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
