"""R330 backfill - re-run the Track 1 consolidation evidence (new wordings) where it is empty.

Scope (fiscal_year >= 2015, filings.consolidation_evidence IS NULL):
  1. the source filings of std consolidated rows that are the separate fallback without evidence
     (consolidation_status = 'fallback_unconfirmed');
  2. the last filing of every (corp, year, period) slot with 2+ filings where an earlier filing
     has consolidated rows (R326 reads the last filing's evidence).
Only an empty column is filled. --apply logs every filled row in
public.consolidation_evidence_r330_20261117 (rcept_no, corp_code).

Usage:
    python scripts/backfill_consolidation_evidence_r330_2026-11-17.py            # dry run
    python scripts/backfill_consolidation_evidence_r330_2026-11-17.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from collector.raw_paths import on_disk_str  # noqa: E402
from fin2.extract.consolidation_evidence import resolve_filing_evidence  # noqa: E402

_SQL = text("""
    WITH src AS (
        SELECT DISTINCT r.value AS rcept_no
        FROM std_financials_v3 s CROSS JOIN LATERAL jsonb_each_text(s.source_rcepts) r
        WHERE s.fiscal_year >= 2015 AND s.statement_type = 'consolidated'
          AND s.consolidation_status = 'fallback_unconfirmed'),
    slots AS (
        SELECT corp_code, fiscal_year, fiscal_period,
               (array_agg(rcept_no ORDER BY filed_at, rcept_no))[count(*)] AS last_r
        FROM filings WHERE fiscal_year >= 2015 GROUP BY 1, 2, 3 HAVING count(*) >= 2),
    lastf AS (
        SELECT p.last_r AS rcept_no FROM slots p
        WHERE EXISTS (SELECT 1 FROM filings g JOIN report_lines r ON r.rcept_no = g.rcept_no
                      AND r.basis = 'consolidated'
                      WHERE g.corp_code = p.corp_code AND g.fiscal_year = p.fiscal_year
                        AND g.fiscal_period = p.fiscal_period AND g.rcept_no <> p.last_r)),
    t AS (SELECT rcept_no FROM src UNION SELECT rcept_no FROM lastf)
    SELECT f.rcept_no, f.corp_code,
           CASE WHEN d.status = 'completed' AND d.file_type = 'xml' THEN d.file_path
                WHEN d.viewer_xml_path IS NOT NULL THEN d.viewer_xml_path
                ELSE d.file_path END AS fp
    FROM t JOIN filings f USING (rcept_no) JOIN download_tasks d USING (rcept_no)
    WHERE f.fiscal_year >= 2015 AND f.consolidation_evidence IS NULL
    ORDER BY f.rcept_no
""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    n_hit = 0
    with get_session() as s:
        if args.apply:
            s.execute(text("CREATE TABLE IF NOT EXISTS public.consolidation_evidence_r330_20261117 "
                           "(rcept_no text PRIMARY KEY, corp_code text)"))
        rows = s.execute(_SQL).fetchall()
        print(f"대상 필링 {len(rows)}", flush=True)
        for i, r in enumerate(rows, 1):
            if not r.fp:
                continue
            ev, det = resolve_filing_evidence(s, r.rcept_no, file_path=on_disk_str(r.fp))
            if ev:
                n_hit += 1
                if args.apply:
                    s.execute(text("UPDATE filings SET consolidation_evidence = :e, "
                                   "consolidation_evidence_detail = CAST(:d AS jsonb) "
                                   "WHERE rcept_no = :r AND consolidation_evidence IS NULL"),
                              {"e": ev, "d": json.dumps(det, ensure_ascii=False), "r": r.rcept_no})
                    s.execute(text("INSERT INTO public.consolidation_evidence_r330_20261117 VALUES (:r, :c) "
                                   "ON CONFLICT DO NOTHING"), {"r": r.rcept_no, "c": r.corp_code})
            if i % 500 == 0:
                if args.apply:
                    s.commit()
                print(f"  {i}/{len(rows)} evidence {n_hit}", flush=True)
        if args.apply:
            s.commit()
    print(f"evidence {n_hit} / {len(rows)}", "applied" if args.apply else "dry run")


if __name__ == "__main__":
    main()
