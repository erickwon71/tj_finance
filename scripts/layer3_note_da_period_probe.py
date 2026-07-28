"""
Layer 3 note->D&A period-identification probe (READ-ONLY).

Context (handoff 2026-07-26 §3.2 / §4-1)
----------------------------------------
D&A is present in `note_lines` for essentially every corp, but the *current*
period cannot be read off `col_index` / `context_fiscal_year`: in the
`비용의 성격별 분류` note the current-year and prior-year figures are emitted as
two SEPARATE tables, both with `col_index = 0` and `context_fiscal_year IS NULL`.
`table_title` is unusable too (the 2nd table's title is bleed-over text from the
1st table's cells).

The working hypothesis is: **within one note section, the smallest `table_seq`
is the current period.** This probe tests that hypothesis without needing any
external ground truth, using cross-report self-consistency:

    report FY(Y)   "current period"  D&A
      must equal
    report FY(Y+1) "prior period"    D&A

If the ordering rule is right, that identity holds. If the rule is backwards for
a corp, the values match after swapping (reported as SWAPPED). Anything else is
UNKNOWN/MISMATCH and needs eyeballing against the DART original.

This script writes nothing to the DB.

Usage
-----
    python scripts/layer3_note_da_period_probe.py --corps 200 --year 2024
    python scripts/layer3_note_da_period_probe.py --corps 50 --basis separate -v
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session


# ── D&A label normalization ────────────────────────────────────────────────
# Handoff §3.2-2: labels vary as 감가상각비 / 감가상각비에 대한 조정 /
# 감가상각비, 유형자산 / 감가상각비, 사용권자산 (the last must be SUMMED into
# depreciation), while 무형자산상각비 stays separate.
#
# (bucket, include patterns (AND), exclude patterns (NOT ANY))
_DA_PATTERNS: list[tuple[str, list[str], list[str]]] = [
    ("amort", ["무형자산상각비"], []),
    ("amort", ["무형자산", "상각"], ["감가상각비"]),
    ("dep", ["감가상각비"], ["무형"]),
    ("dep", ["감가상각"], ["무형"]),
]

# Lines that are totals/subtotals rather than the D&A line itself.
_TOTAL_HINT = re.compile(r"(합\s*계|총\s*계|소\s*계)")


def classify_label(label: str) -> Optional[str]:
    """Map a raw note label to 'dep' / 'amort' / None."""
    norm = re.sub(r"\s+", "", label or "")
    if not norm:
        return None
    if _TOTAL_HINT.search(norm):
        return None
    for bucket, inc, exc in _DA_PATTERNS:
        if all(p in norm for p in inc) and not any(p in norm for p in exc):
            return bucket
    return None


# ── data access ────────────────────────────────────────────────────────────
FETCH_SQL = text(
    """
    SELECT rcept_no, section_path, table_seq, row_order, col_index,
           label_raw, value_won
    FROM note_lines
    WHERE corp_code = :corp
      AND report_fiscal_year = :year
      AND report_fiscal_period = 'FY'
      AND basis = :basis
      AND statement = 'note'
      AND value_won IS NOT NULL
    """
)


def sample_corps(session, n: int, seed: int) -> list[str]:
    """Corps that exist in std_v3 (the Layer 3 target universe)."""
    rows = session.execute(
        text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
    ).fetchall()
    corps = [r[0] for r in rows]
    rng = random.Random(seed)
    rng.shuffle(corps)
    return corps[:n]


def fetch_da_tables(
    session, corp: str, year: int, basis: str, section_pat: str
) -> dict[tuple[str, int], dict]:
    """
    Return {(section_path, table_seq): {'dep': v, 'amort': v, 'multicol': bool}}
    for note tables matching `section_pat` that contain at least one D&A line.

    Bounded by corp_code (index-backed); section filtering happens in Python
    because `section_path` has no index and LIKE '%..%' would full-scan.
    """
    rows = session.execute(
        FETCH_SQL, {"corp": corp, "year": year, "basis": basis}
    ).fetchall()
    if not rows:
        return {}

    # Amendments: several rcept_no can exist for one (corp, year, FY). Keep the
    # latest filing only.
    latest = max(r.rcept_no for r in rows)

    tables: dict[tuple[str, int], dict] = defaultdict(
        lambda: {"dep": None, "amort": None, "multicol": False, "n_lines": 0}
    )
    for r in rows:
        if r.rcept_no != latest:
            continue
        if section_pat not in (r.section_path or ""):
            continue
        bucket = classify_label(r.label_raw)
        if bucket is None:
            continue
        key = (r.section_path, r.table_seq)
        entry = tables[key]
        entry["n_lines"] += 1
        if (r.col_index or 0) > 0:
            entry["multicol"] = True
            continue  # current period is col_index=0 when columns are used
        # Sum: 감가상각비, 유형자산 + 감가상각비, 사용권자산 both land in 'dep'.
        prev = entry[bucket]
        entry[bucket] = r.value_won if prev is None else prev + r.value_won

    return dict(tables)


def ordered_periods(tables: dict[tuple[str, int], dict]) -> list[dict]:
    """
    Apply the hypothesis: within a section, ascending table_seq == period order
    (current first, then prior). Returns the per-period D&A dicts of the section
    that carries the most D&A signal.
    """
    if not tables:
        return []
    by_section: dict[str, list] = defaultdict(list)
    for (section, seq), entry in tables.items():
        by_section[section].append((seq, entry))
    # Prefer the section with the most D&A lines (avoids picking a stray table).
    best = max(
        by_section.items(), key=lambda kv: sum(e["n_lines"] for _, e in kv[1])
    )
    return [entry for _, entry in sorted(best[1], key=lambda t: t[0])]


def same(a: Optional[int], b: Optional[int], rel_tol: float = 1e-6) -> bool:
    """
    Equal within rounding noise. Values are reconstructed from rounded
    presentation units (백만원 etc.) and summed across sub-lines, so exact
    equality is too strict — observed drift is a few won on 10^10 magnitudes.
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) <= max(scale * rel_tol, 1_000)


def _rel_gap(a: Optional[int], b: Optional[int]) -> Optional[float]:
    if a is None or b is None:
        return None
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def _nearest_verdict(cur, prior_slot, cur_slot) -> str:
    """
    Compare cur(Y) against both slots of FY(Y+1). Nearer 'prior' slot supports
    the ascending-table_seq rule; nearer 'current' slot contradicts it.
    """
    votes = []
    for field in ("dep", "amort"):
        g_prior = _rel_gap(cur[field], prior_slot[field])
        g_cur = _rel_gap(cur[field], cur_slot[field])
        if g_prior is None or g_cur is None:
            continue
        votes.append(g_prior < g_cur)
    if not votes:
        return "NO_COMPARABLE"
    if all(votes):
        return "NEAR_PRIOR(restated)"
    if not any(votes):
        return "NEAR_CURRENT(contradicts)"
    return "MIXED_SIGNAL"


def normalize_section(section: str) -> str:
    """'29. 비용의 성격별 분류 (연결)' -> '비용의 성격별 분류' (for tallying)."""
    s = (section or "").strip()
    s = re.sub(r"^[\s\d]*[.．]\s*", "", s)          # leading note number
    s = re.sub(r"[(（]\s*(연결|별도)\s*[)）]", "", s)  # trailing basis marker
    return re.sub(r"\s+", " ", s).strip()


def diagnose(session, corps: list[str], year: int, basis: str) -> None:
    """
    Which note sections actually carry D&A lines? Answers whether
    '비용의 성격별 분류' is a viable PRIMARY source or only one of several.
    """
    section_hits: Counter[str] = Counter()
    section_example: dict[str, str] = {}
    corps_with_any = 0
    per_corp_sections: Counter[int] = Counter()

    for corp in corps:
        rows = session.execute(
            FETCH_SQL, {"corp": corp, "year": year, "basis": basis}
        ).fetchall()
        if not rows:
            continue
        latest = max(r.rcept_no for r in rows)
        found: set[str] = set()
        for r in rows:
            if r.rcept_no != latest:
                continue
            if classify_label(r.label_raw) is not None:
                found.add(normalize_section(r.section_path))
        if found:
            corps_with_any += 1
            per_corp_sections[len(found)] += 1
            for s in found:
                section_hits[s] += 1
                section_example.setdefault(s, corp)

    n = len(corps)
    print(f"\n=== D&A-bearing note sections · FY{year} · {basis} (n={n} corps) ===")
    print(f"corps with >=1 D&A note line: {corps_with_any} ({corps_with_any / n * 100:.1f}%)")
    print("\n  sections by corp coverage:")
    for sec, cnt in section_hits.most_common(25):
        print(f"    {cnt:>4} ({cnt / n * 100:5.1f}%)  {sec[:60]:<60} eg={section_example[sec]}")
    print("\n  distinct D&A sections per corp:")
    for k, v in sorted(per_corp_sections.items()):
        print(f"    {k} section(s): {v} corps")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=200, help="sample size")
    ap.add_argument("--year", type=int, default=2024, help="base report FY")
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--section", default="비용의 성격별", help="note section filter")
    ap.add_argument("--seed", type=int, default=20260727)
    ap.add_argument(
        "--diagnose",
        action="store_true",
        help="tally which note sections carry D&A instead of testing the ordering rule",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.diagnose:
        with get_session() as session:
            corps = sample_corps(session, args.corps, args.seed)
            diagnose(session, corps, args.year, args.basis)
        return 0

    y0, y1 = args.year, args.year + 1
    verdicts: Counter[str] = Counter()
    shapes: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    with get_session() as session:
        corps = sample_corps(session, args.corps, args.seed)
        print(
            f"probe: {len(corps)} corps · FY{y0} vs FY{y1} · basis={args.basis} "
            f"· section~'{args.section}'"
        )

        for corp in corps:
            t0 = fetch_da_tables(session, corp, y0, args.basis, args.section)
            t1 = fetch_da_tables(session, corp, y1, args.basis, args.section)
            p0, p1 = ordered_periods(t0), ordered_periods(t1)

            if not p0 or not p1:
                verdicts["NO_SECTION"] += 1
                continue

            # Shape of the base-year section.
            if any(e["multicol"] for e in p0):
                shapes["MULTICOL_TABLE"] += 1
            elif len(p0) == 1:
                shapes["SINGLE_TABLE"] += 1
            elif len(p0) == 2:
                shapes["TWO_TABLES"] += 1
            else:
                shapes[f"N_TABLES({len(p0)})"] += 1

            if len(p0) < 1 or len(p1) < 2:
                verdicts["NO_PRIOR_IN_Y1"] += 1
                continue

            cur_y0 = p0[0]                       # hypothesis: current period
            prior_y1 = p1[1]                     # hypothesis: prior period
            alt_y1 = p1[0]                       # if ordering were reversed

            hit = same(cur_y0["dep"], prior_y1["dep"]) or same(
                cur_y0["amort"], prior_y1["amort"]
            )
            swap = same(cur_y0["dep"], alt_y1["dep"]) or same(
                cur_y0["amort"], alt_y1["amort"]
            )

            if hit and not swap:
                verdict = "CONFIRMED"
            elif hit and swap:
                verdict = "AMBIGUOUS"        # both match (e.g. flat values)
            elif swap:
                verdict = "SWAPPED"          # hypothesis backwards here
            else:
                # Neither matches exactly. Restatements make FY(Y+1)'s prior
                # column drift from FY(Y)'s current. The ordering rule still
                # holds if the "prior" slot is nearer than the "current" slot;
                # only the opposite would contradict it.
                verdict = _nearest_verdict(cur_y0, prior_y1, alt_y1)
            verdicts[verdict] += 1

            if verdict != "CONFIRMED" and len(examples[verdict]) < 8:
                examples[verdict].append(
                    f"{corp}: FY{y0}.cur dep={cur_y0['dep']} amort={cur_y0['amort']} | "
                    f"FY{y1}.prior dep={prior_y1['dep']} amort={prior_y1['amort']} | "
                    f"FY{y1}.cur dep={alt_y1['dep']} amort={alt_y1['amort']}"
                )
            if args.verbose:
                print(f"  {corp} {verdict}")

    total = sum(verdicts.values())
    print(f"\n=== verdicts (n={total}) ===")
    for k, v in verdicts.most_common():
        print(f"  {k:<14} {v:>5}  {v / total * 100:5.1f}%")

    decided = verdicts["CONFIRMED"] + verdicts["SWAPPED"]
    if decided:
        print(
            f"\n  ordering rule holds: {verdicts['CONFIRMED']}/{decided} = "
            f"{verdicts['CONFIRMED'] / decided * 100:.1f}% of decidable cases"
        )

    print(f"\n=== section shapes (FY{y0}) ===")
    for k, v in shapes.most_common():
        print(f"  {k:<18} {v:>5}")

    for verdict, rows in examples.items():
        if rows:
            print(f"\n--- {verdict} examples ---")
            for line in rows:
                print(f"  {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
