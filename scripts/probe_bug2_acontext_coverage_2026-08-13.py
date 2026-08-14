"""Probe (read-only) — ACODE/ACONTEXT (Track A inline XBRL) coverage across the corpus.

Background: Gate B bug#2(dividends_paid sign) investigation found that document.xml often
carries inline TE[@ACODE]/[@ACONTEXT] tags that fin2/audit/face_audit.py (Track A reader,
audit-only) already reads and gets the correct signed value from, but the production layer2
extractor (fin2/extract/report_lines.py) never reads this tag at all (pure text/table scan).

Question this probe answers: across the whole filing corpus, what fraction of filings actually
carry usable ACODE+ACONTEXT cells (Track A eligible), broken down by fiscal_year / report_type /
statement area (CF specifically, since that's where bug#2 lives) — so we know whether extending
report_lines.py to read this tag is worth it broadly or only helps a narrow slice (precedent:
fin2/extract/report_lines.py already notes ComponentsOfEquityAxis ACONTEXT coverage is only
21.5%, "Track A 만 마킹").

Read-only: no DB writes, no source code changes. Reuses the exact same reader helpers face_audit.py
uses (parser/xml/dart_xml_parser.py::_parse_xml_file which applies sanitize_dart_xml, and
fin2/extract/acontext.py::parse_acontext) so results are directly comparable to what the audit
tool already sees — not a fresh reimplementation subject to its own bugs.
"""
from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.acontext import parse_acontext

_XBRL_PREFIXES = ("ifrs-full_", "dart_")

# CF concepts relevant to dividends_paid (both ifrs-full and dart namespaces observed in the
# codebase's own concept_map.py CF section — kept loose/prefix-based, this is a coverage probe
# not a canonical mapper).
_DIVIDEND_HINTS = ("Dividend",)

SAMPLE_PER_CELL = 20
SEED = 42


def stratified_sample(session):
    """Stratify by (fiscal_year, report_type), sample up to SAMPLE_PER_CELL each."""
    rows = session.execute(text("""
        SELECT dt.rcept_no, dt.file_path, f.fiscal_year, f.report_type, f.corp_code
        FROM download_tasks dt
        JOIN filings f ON f.rcept_no = dt.rcept_no
        JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
        WHERE dt.file_type = 'xml' AND dt.status = 'completed' AND dt.file_path IS NOT NULL
          AND f.fiscal_year IS NOT NULL
    """)).fetchall()

    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        buckets[(r.fiscal_year, r.report_type)].append(r)

    rng = random.Random(SEED)
    sample = []
    for key, items in buckets.items():
        rng.shuffle(items)
        sample.extend(items[:SAMPLE_PER_CELL])
    return sample


def probe_file(file_path: str) -> dict:
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return {"parse_ok": False}

    te_acode = root.findall(".//TE[@ACODE]")
    n_total = len(te_acode)
    n_track_a = 0          # ACODE has ifrs-full_/dart_ prefix
    n_with_acontext = 0    # ...and ACONTEXT attr non-empty
    n_acontext_parsed = 0  # ...and parse_acontext() succeeds
    n_cf_track_a = 0       # Track A cells whose ACODE looks CF-ish (dart CF namespace convention)
    n_dividend_track_a = 0

    for te in te_acode:
        acode = te.get("ACODE", "")
        if not acode.startswith(_XBRL_PREFIXES) or len(acode) > 255:
            continue
        n_track_a += 1
        acontext = te.get("ACONTEXT", "")
        if not acontext:
            continue
        n_with_acontext += 1
        ctx = parse_acontext(acontext)
        if ctx.parsed:
            n_acontext_parsed += 1
        if "CF" in acode or "CashFlow" in acode:
            n_cf_track_a += 1
        if any(h in acode for h in _DIVIDEND_HINTS):
            n_dividend_track_a += 1

    return {
        "parse_ok": True,
        "n_total_te_acode": n_total,
        "n_track_a": n_track_a,
        "n_with_acontext": n_with_acontext,
        "n_acontext_parsed": n_acontext_parsed,
        "n_cf_track_a": n_cf_track_a,
        "n_dividend_track_a": n_dividend_track_a,
    }


def main():
    init_db()
    with get_session() as s:
        sample = stratified_sample(s)

    print(f"표본 {len(sample)}건 (fiscal_year x report_type 층화, 셀당 최대 {SAMPLE_PER_CELL}건)")

    by_year: dict[int, Counter] = defaultdict(Counter)
    by_report_type: dict[str, Counter] = defaultdict(Counter)
    overall = Counter()
    parse_fail = 0

    for i, row in enumerate(sample, 1):
        result = probe_file(row.file_path)
        if not result["parse_ok"]:
            parse_fail += 1
            continue

        has_track_a = result["n_with_acontext"] > 0
        has_cf_track_a = result["n_cf_track_a"] > 0
        has_dividend_track_a = result["n_dividend_track_a"] > 0

        overall["n_files"] += 1
        overall["n_has_track_a"] += int(has_track_a)
        overall["n_has_cf_track_a"] += int(has_cf_track_a)
        overall["n_has_dividend_track_a"] += int(has_dividend_track_a)
        overall["sum_te_acode"] += result["n_total_te_acode"]
        overall["sum_with_acontext"] += result["n_with_acontext"]

        by_year[row.fiscal_year]["n_files"] += 1
        by_year[row.fiscal_year]["n_has_track_a"] += int(has_track_a)

        by_report_type[row.report_type]["n_files"] += 1
        by_report_type[row.report_type]["n_has_track_a"] += int(has_track_a)

        if i % 200 == 0:
            print(f"  ..{i}/{len(sample)}")

    print()
    print(f"파싱 실패: {parse_fail}/{len(sample)}")
    print()
    print("=== 종합 ===")
    n = overall["n_files"]
    if n:
        print(f"전체 표본: {n}건")
        print(f"  ACODE+ACONTEXT(Track A) 보유 필링: {overall['n_has_track_a']}건 "
              f"({100*overall['n_has_track_a']/n:.1f}%)")
        print(f"  그중 CF 관련 acode 보유: {overall['n_has_cf_track_a']}건 "
              f"({100*overall['n_has_cf_track_a']/n:.1f}%)")
        print(f"  그중 배당 관련(Dividend) acode 보유: {overall['n_has_dividend_track_a']}건 "
              f"({100*overall['n_has_dividend_track_a']/n:.1f}%)")

    print()
    print("=== fiscal_year 별 Track A 보유율 ===")
    for year in sorted(by_year):
        c = by_year[year]
        if c["n_files"]:
            print(f"  {year}: {c['n_has_track_a']}/{c['n_files']} "
                  f"({100*c['n_has_track_a']/c['n_files']:.1f}%)")

    print()
    print("=== report_type 별 Track A 보유율 ===")
    for rt in sorted(by_report_type):
        c = by_report_type[rt]
        if c["n_files"]:
            print(f"  {rt}: {c['n_has_track_a']}/{c['n_files']} "
                  f"({100*c['n_has_track_a']/c['n_files']:.1f}%)")


if __name__ == "__main__":
    main()
