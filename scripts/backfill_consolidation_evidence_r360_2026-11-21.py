"""R360/R361 (2026-11-21): re-judge filings.consolidation_evidence for the periods whose std row was a
copy of the other basis without evidence before R359 (public.r359_std_before_20261121): consolidated
copies (R360 wordings) and separate copies (R361 "4. 재무제표" pointing to section 2). Only these
periods can change: every other FY2015+ fallback row already had evidence.

Usage:
    python scripts/backfill_consolidation_evidence_r360_2026-11-21.py           # dry run
    python scripts/backfill_consolidation_evidence_r360_2026-11-21.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract import consolidation_evidence as ce  # noqa: E402

_NAS = "/Users/taejin/Project/tj_finance/raw_report"
_SD = "/Volumes/dart_data/raw_report"

_TARGETS = text("""
    SELECT DISTINCT f.rcept_no, f.consolidation_evidence AS old, dt.file_path
    FROM r359_std_before_20261121 b
    JOIN filings f ON f.corp_code = b.corp_code AND f.fiscal_year = b.fiscal_year
                  AND f.fiscal_period = b.fiscal_period
    LEFT JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE (b.statement_type = 'consolidated' AND b.consolidation_status = 'fallback_unconfirmed')
       OR (b.statement_type = 'separate' AND b.basis_fallback)
    ORDER BY f.rcept_no
""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    stat: Counter = Counter()
    with get_session() as s:
        for r in s.execute(_TARGETS).fetchall():
            fp = r.file_path
            if fp and fp.startswith(_NAS) and os.path.exists(_SD + fp[len(_NAS):]):
                fp = _SD + fp[len(_NAS):]
            if args.apply:
                new = ce.store_filing_consolidation_evidence(s, r.rcept_no, file_path=fp)
            else:
                new, _ = ce.resolve_filing_evidence(s, r.rcept_no, file_path=fp)
            stat[(r.old, new)] += 1
            if r.old != new:
                print(f"  {r.rcept_no}: {r.old} -> {new}")
        if args.apply:
            s.commit()
    print(dict(stat), "applied" if args.apply else "dry run")


if __name__ == "__main__":
    main()
