"""
Layer 2.5 note-heading recovery probe (READ-ONLY).

Why
---
Layer 3 needs to know *which note* every note table belongs to — not just for
D&A but for every note-derived item (R&D, leases, segments, employee benefits).
Today `section_path` resolves for only ~23% of corps; for ~57.5% every note line
collapses under a single '3. 연결재무제표 주석', because those filings carry the
per-note headings as plain <P> text rather than <TITLE> elements, and DART XML
has no per-note structural marker (AASSOCNOTE is TOC-level only).

Key observation this probe tests: the heading text is NOT lost. It survives in
`note_lines.table_title` ('30. 비용의 성격별 분류 (1) 보고기간 중 …'), so note
structure can be rebuilt inside the DB with no re-parse of the raw XML.

Method
------
1. Per filing, take distinct (table_seq, table_title).
2. Parse a leading note number + title out of table_title.
3. Forward-fill by ascending table_seq: continuation tables (NULL title, or a
   sub-item like '(4) …') inherit the nearest preceding heading.
4. Score:
   - coverage    : % of tables that end up assigned to a note
   - monotonic   : note numbers should be non-decreasing along table_seq
                   (a cheap structural sanity check)
   - AGREEMENT   : on filings where `section_path` already resolves, compare the
                   recovered note number/title against section_path. That is
                   ground truth, so it validates the method before applying it
                   to the collapsed majority.

Writes nothing to the DB.

Usage
-----
    python scripts/layer25_note_heading_recovery_probe.py --corps 200
    python scripts/layer25_note_heading_recovery_probe.py --show 00540863
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

# '30. 비용의 성격별 분류 (1) 보고기간 중 …' -> (30, '비용의 성격별 분류')
# The heading runs until a sub-item marker '(1)', a sentence, or end of string.
# The negative lookahead rejects multi-level numbering ('1.1.5 주요 종속기업…'),
# which is a sub-item of note 1, not a note heading.
_HEADING = re.compile(
    r"^\s*(\d{1,2})\s*[.．]\s*(?!\d)(.+?)\s*(?=[(（]\s*\d+\s*[)）]|보고기간|당기말|$)"
)
# Sub-item continuation: '(4) 보고기간 중 …' — inherits the preceding heading.
_SUBITEM = re.compile(r"^\s*[(（]\s*\d+\s*[)）]")
# Trailing basis marker on titles: '유형자산 (연결)'
_BASIS_TAIL = re.compile(r"\s*[(（]\s*(연결|별도)\s*[)）]\s*$")

TABLES_SQL = text(
    """
    SELECT DISTINCT table_seq, table_title, section_path
    FROM note_lines
    WHERE corp_code = :corp
      AND rcept_no = :rcept
      AND basis = :basis
      AND statement = 'note'
      AND table_seq IS NOT NULL
    """
)

# Source the filing list from `filings` (small, PK on rcept_no) rather than from
# note_lines. The equivalent ORDER BY rcept_no DESC LIMIT 1 against note_lines
# picks a pathological plan on some corps (observed >4 min for a single corp).
FILINGS_SQL = text(
    """
    SELECT corp_code, max(rcept_no) AS rcept_no
    FROM filings
    WHERE fiscal_year = :year
      AND fiscal_period = 'FY'
      AND report_type = 'annual'
      AND is_final
    GROUP BY corp_code
    """
)


def clean_title(t: str) -> str:
    t = _BASIS_TAIL.sub("", (t or "").strip())
    return re.sub(r"\s+", " ", t).strip()


def parse_heading(title: Optional[str]) -> Optional[tuple[int, str]]:
    """Extract (note_no, note_title) from a table_title, if it starts one."""
    if not title:
        return None
    s = title.strip()
    if _SUBITEM.match(s):
        return None
    m = _HEADING.match(s)
    if not m:
        return None
    no = int(m.group(1))
    name = clean_title(m.group(2))
    # Reject junk: bleed-over text from a previous table's cells tends to be
    # long and to contain digits/commas from numbers.
    if not name or len(name) > 40 or re.search(r"\d{3}", name):
        return None
    return no, name


def recover(rows) -> list[dict]:
    """Assign each table a note via heading parse + forward-fill on table_seq."""
    out: list[dict] = []
    cur: Optional[tuple[int, str]] = None
    for r in sorted(rows, key=lambda r: r.table_seq):
        head = parse_heading(r.table_title)
        if head is not None:
            cur = head
            origin = "heading"
        else:
            origin = "inherited" if cur is not None else "none"
        out.append(
            {
                "table_seq": r.table_seq,
                "note_no": cur[0] if cur else None,
                "note_title": cur[1] if cur else None,
                "origin": origin,
                "section_path": r.section_path,
            }
        )
    return out


def section_is_resolved(rows) -> bool:
    paths = {(r.section_path or "") for r in rows}
    if len(paths) <= 1:
        return False
    generic = all(
        re.match(r"^\s*(?:\d+\s*[.．]\s*)?(?:연결)?재무제표\s*주석\s*$", p) for p in paths
    )
    return not generic


def section_note_no(section_path: str) -> Optional[int]:
    m = re.match(r"^\s*(\d{1,2})\s*[.．]", section_path or "")
    return int(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=200)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--seed", type=int, default=20260727)
    ap.add_argument("--show", help="dump recovery for one corp_code")
    args = ap.parse_args()

    with get_session() as session:
        latest_by_corp = {
            r.corp_code: r.rcept_no
            for r in session.execute(FILINGS_SQL, {"year": args.year}).fetchall()
        }

        if args.show:
            rcept = latest_by_corp.get(args.show)
            rows = session.execute(
                TABLES_SQL,
                {"corp": args.show, "rcept": rcept, "basis": args.basis},
            ).fetchall()
            print(f"corp={args.show} rcept={rcept} tables={len(rows)}")
            for rec in recover(rows):
                print(
                    f"  seq={rec['table_seq']:>4} note={str(rec['note_no']):>4}. "
                    f"{str(rec['note_title'])[:34]:<34} [{rec['origin']}]"
                )
            return 0

        corps = [
            r[0]
            for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        origin_tally: Counter[str] = Counter()
        monotonic = Counter()
        agree = Counter()
        filings = Counter()
        disagreements: list[str] = []

        for corp in corps:
            rcept = latest_by_corp.get(corp)
            if not rcept:
                filings["NO_NOTES"] += 1
                continue
            rows = session.execute(
                TABLES_SQL, {"corp": corp, "rcept": rcept, "basis": args.basis}
            ).fetchall()
            if not rows:
                filings["NO_TABLES"] += 1
                continue
            filings["OK"] += 1

            recs = recover(rows)
            for rec in recs:
                origin_tally[rec["origin"]] += 1

            nos = [r["note_no"] for r in recs if r["note_no"] is not None]
            monotonic["yes" if nos == sorted(nos) else "no"] += 1

            # Validate against section_path where it is genuine ground truth.
            if section_is_resolved(rows):
                for rec in recs:
                    truth = section_note_no(rec["section_path"])
                    if truth is None or rec["note_no"] is None:
                        continue
                    if truth == rec["note_no"]:
                        agree["MATCH"] += 1
                    else:
                        # Direction tells us the mechanism: 'lags' means the
                        # heading for the true note was never captured, so the
                        # table inherited an earlier note (over-inheritance).
                        agree["DIFF_lags" if rec["note_no"] < truth else "DIFF_ahead"] += 1
                        agree["DIFF"] += 1
                        if len(disagreements) < 10:
                            disagreements.append(
                                f"{corp} seq={rec['table_seq']} "
                                f"recovered={rec['note_no']}.{rec['note_title']} "
                                f"section={rec['section_path'][:40]!r}"
                            )

    print(f"=== filings (n={sum(filings.values())}) ===")
    for k, v in filings.most_common():
        print(f"  {k:<10} {v:>5}")

    tot = sum(origin_tally.values())
    print(f"\n=== table note-assignment origin (n={tot} tables) ===")
    for k, v in origin_tally.most_common():
        print(f"  {k:<10} {v:>6}  {v / tot * 100:5.1f}%")
    assigned = tot - origin_tally.get("none", 0)
    print(f"  --> assigned: {assigned}/{tot} = {assigned / tot * 100:.1f}%")

    print("\n=== note-number monotonicity per filing ===")
    for k, v in monotonic.most_common():
        print(f"  {k:<5} {v:>5}")

    a_tot = sum(agree.values())
    if a_tot:
        print(f"\n=== AGREEMENT vs resolved section_path (n={a_tot} tables) ===")
        for k, v in agree.most_common():
            print(f"  {k:<6} {v:>6}  {v / a_tot * 100:5.1f}%")
    if disagreements:
        print("\n--- disagreement examples ---")
        for d in disagreements:
            print(f"  {d}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
