"""R325 backfill: consolidation evidence of XBRL-zip / PDF filings from their web-view print.

filings.consolidation_evidence was never set for filings whose download is an XBRL zip or a PDF
(resolve_filing_evidence only read a .xml file); R325 reads <rcept>.viewer.xml next to it.
Target: 2015+ filings (Track 1 is valid from 2015) with a non-xml download and no evidence yet.

Usage: python scripts/backfill_consolidation_evidence_viewer_r325_2026-11-17.py [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.consolidation_evidence import (  # noqa: E402
    resolve_filing_evidence, store_filing_consolidation_evidence)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    with get_session() as s:
        rows = s.execute(text("""
            SELECT f.rcept_no, dt.file_path FROM filings f JOIN download_tasks dt USING (rcept_no)
            WHERE dt.file_type <> 'xml' AND dt.file_path IS NOT NULL AND f.fiscal_year >= 2015
              AND f.consolidation_evidence IS NULL ORDER BY f.rcept_no""")).fetchall()
        stat: Counter = Counter()
        for i, (rcept, fp) in enumerate(rows, 1):
            if args.apply:
                ev = store_filing_consolidation_evidence(s, rcept, file_path=fp)
            else:
                ev, _ = resolve_filing_evidence(s, rcept, file_path=fp)
            stat[ev or "none"] += 1
            if args.apply and i % 200 == 0:
                s.commit()
        if args.apply:
            s.commit()
    print(f"filings {len(rows)}: {dict(stat)}" + (" (applied)" if args.apply else " (dry run)"))


if __name__ == "__main__":
    main()
