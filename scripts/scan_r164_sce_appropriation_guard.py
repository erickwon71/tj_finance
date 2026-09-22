#!/usr/bin/env python
"""R164 scale scanner - SCE tables dropped by the appropriation-statement guard.

## What it measures (not a proxy)

`_detect_body_statement_tables()` drops any data table whose row labels look
like an appropriation statement (`_looks_like_appropriation`). That predicate
needs TWO things: an appropriation account present AND no "real statement"
account (`자산총계`/`매출액`/`영업활동현금흐름`...). For BS/IS/CF the second
condition is a genuine discriminator. **For SCE it can never fire** - an SCE's
row labels are change reasons and its header row carries equity component
names, so `_REAL_STMT_ROW_RE` never matches. Any SCE whose labels contain
`미처분이익잉여금` (a perfectly normal equity component) is therefore dropped
whole.

So this scanner does not guess: for each filing it re-runs the REAL detector
and reports, per SCE table this guard decides, whether the detector now keeps
it (`recovered`) or still drops it (`dropped`). It is therefore a progress
meter, not a fingerprint counter - an earlier version counted the fingerprint
and kept reporting the same number after the fix, because the fix changes the
outcome, not the predicates.

## Usage

    python scripts/scan_r164_sce_appropriation_guard.py --rcept-file <path>
    python scripts/scan_r164_sce_appropriation_guard.py --limit 300 --sample
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.statement_titles import (
    classify_statement_in_body_section, title_text_for_classify,
    title_text_owned,
)
from fin2.extract.report_lines import _detect_fin_type, _parse_xml_file
from fin2.extract.text import (
    _detect_body_statement_tables, _looks_like_appropriation,
    _looks_like_equity_changes_header, _table_has_data_rows,
)
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, assign_tables_to_dart_sections,
)

_NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"

# Filings where a basis has BS/IS/CF loaded but no SCE at all. Superset of the
# defect: the source may genuinely carry no SCE for that basis.
_CANDIDATE_SQL = """
WITH s AS (
    SELECT rcept_no, basis,
           count(*) FILTER (WHERE statement='BS')  AS bs,
           count(*) FILTER (WHERE statement='IS')  AS is_,
           count(*) FILTER (WHERE statement='CF')  AS cf,
           count(*) FILTER (WHERE statement='SCE') AS sce
    FROM report_lines
    WHERE report_fiscal_year >= 2015
    GROUP BY 1,2
)
SELECT DISTINCT s.rcept_no
FROM s
WHERE s.sce = 0 AND s.bs > 0 AND s.is_ > 0 AND s.cf > 0
ORDER BY 1
"""

_PATH_SQL = """
    SELECT dt.rcept_no, dt.file_path, c.corp_name, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN corporations c USING (corp_code)
    WHERE dt.rcept_no = ANY(:rcepts)
"""


def _sd_path(file_path: str) -> Path:
    """Read from the SD card - bulk XML reads over the NAS stall (memory rule)."""
    if file_path and file_path.startswith(_NAS_PREFIX):
        return Path(_SD_PREFIX + file_path[len(_NAS_PREFIX):])
    return Path(file_path)


def _sce_state(path: Path) -> list[tuple[str, str, int]]:
    """Return [(basis, state, n_rows)] for every SCE-classified data table.

    state is measured against the REAL detector, not against a fingerprint:

      recovered - the detector now returns the SCE code for that basis
      dropped   - it does not, and this guard is why

    The split matters because the R164 exemption requires POSITIVE SCE
    evidence (`_looks_like_equity_changes_header`). Tables whose equity column
    names sit below the first two rows fail that test and stay dropped - see
    the residual class in docs/PARSING_RULES.md R164.
    """
    root = _parse_xml_file(path)
    if root is None:
        return []
    fin_type = _detect_fin_type(root, file_path=str(path))
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    sec = assign_tables_to_dart_sections(root)
    out: list[tuple[str, str, int]] = []
    for sec_kind, basis, code in ((SEC_CONSOL_FS, "consolidated", "SCE_C"),
                                  (SEC_SEP_FS, "separate", "SCE_S")):
        if basis == "consolidated" and fin_type == "B":
            continue          # the detector ignores these; so must the scanner
        for tbl in sec.get(sec_kind, []):
            stmt = classify_statement_in_body_section(
                title_text_owned(tbl), include_sce=True)
            if stmt is None:
                stmt = classify_statement_in_body_section(
                    title_text_for_classify(tbl), include_sce=True)
            if stmt != "SCE" or not _table_has_data_rows(tbl):
                continue
            if not _looks_like_appropriation(tbl):
                continue      # this guard is not what decides the table
            n = len(list(tbl.iter("TR")))
            if code in groups:
                out.append((basis, "recovered", n))
            else:
                has_hdr = _looks_like_equity_changes_header(tbl)
                out.append((basis, "dropped/hdr=%s" % has_hdr, n))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept-file", help="one rcept_no per line")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", action="store_true",
                    help="evenly spread the limit over the candidate set")
    ap.add_argument("--out", help="write hit rcept_no list here")
    args = ap.parse_args()

    with get_session() as session:
        if args.rcept_file:
            rcepts = [l.strip() for l in open(args.rcept_file) if l.strip()]
        else:
            rcepts = list(session.execute(text(_CANDIDATE_SQL)).scalars().all())
        print("candidate filings: %d" % len(rcepts))

        if args.limit and len(rcepts) > args.limit:
            if args.sample:
                step = len(rcepts) / float(args.limit)
                rcepts = [rcepts[int(i * step)] for i in range(args.limit)]
            else:
                rcepts = rcepts[:args.limit]
            print("scanning: %d" % len(rcepts))

        meta = {r["rcept_no"]: r for r in session.execute(
            text(_PATH_SQL), {"rcepts": rcepts}).mappings()}

    tally: dict[str, int] = {}
    rows_by_state: dict[str, int] = {}
    n_missing = 0
    still_dropped: list[str] = []
    shown = 0
    for i, rcept in enumerate(rcepts, 1):
        m = meta.get(rcept)
        if not m:
            n_missing += 1
            continue
        path = _sd_path(m["file_path"])
        if not path.exists():
            n_missing += 1
            continue
        try:
            found = _sce_state(path)
        except Exception as exc:                        # noqa: BLE001
            print("  ERROR %s %s" % (rcept, exc))
            continue
        for basis, state, n in found:
            key = "%s %s" % (basis, state)
            tally[key] = tally.get(key, 0) + 1
            rows_by_state[state] = rows_by_state.get(state, 0) + n
        dropped = [f for f in found if f[1].startswith("dropped")]
        if dropped:
            still_dropped.append(rcept)
            if shown < 20:
                shown += 1
                print("  DROPPED %s %-14s %s%-4s %s" % (
                    rcept, (m["corp_name"] or "")[:12], m["fiscal_year"],
                    m["fiscal_period"] or "",
                    ", ".join("%s %s %drows" % f for f in dropped)))
        if i % 300 == 0:
            print("  ... %d/%d scanned" % (i, len(rcepts)))

    print("\nscanned=%d  unreadable=%d" % (len(rcepts), n_missing))
    print("SCE tables this guard decides:")
    for k in sorted(tally):
        print("  %-34s %d" % (k, tally[k]))
    print("source rows by state:")
    for k in sorted(rows_by_state):
        print("  %-20s %d" % (k, rows_by_state[k]))
    print("filings still missing an SCE because of this guard: %d"
          % len(still_dropped))

    if args.out and still_dropped:
        Path(args.out).write_text("\n".join(still_dropped) + "\n")
        print("  still-dropped list -> %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
