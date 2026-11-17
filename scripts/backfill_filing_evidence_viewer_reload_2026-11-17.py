"""Fill filings.ifrs_evidence / consolidation_evidence that the web-view print load and the
verification reload never stored (fixed 2026-11-17 in collector/xbrl_instance_lines_sync.
store_filing_evidences).

Scope: final filings, fiscal_year >= 2015, where the column is NULL. Only an empty column is
filled; a value already stored is never changed. Source selection is the one of
fin2.verification.ops._reload_rcept: completed main XML, else the web-view print, else the
XBRL zip (IFRS from the DB track only, consolidation from the print next to it, R325).

--apply writes the filled rows into public.filing_evidence_backfill_20261117
(rcept_no, corp_code, col, new_value) so the change can be listed or undone.

Usage:
    python scripts/backfill_filing_evidence_viewer_reload_2026-11-17.py            # dry run
    python scripts/backfill_filing_evidence_viewer_reload_2026-11-17.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from collector.raw_paths import on_disk_str  # noqa: E402
from fin2.extract import consolidation_evidence as ce  # noqa: E402
from fin2.extract import ifrs_evidence as ie  # noqa: E402

_SQL = text("""
    SELECT f.rcept_no, f.corp_code,
           f.ifrs_evidence IS NULL AS need_ifrs,
           f.consolidation_evidence_detail IS NULL AS need_cons,
           CASE WHEN d.status = 'completed' AND d.file_type = 'xml' THEN d.file_path
                WHEN d.viewer_xml_path IS NOT NULL THEN d.viewer_xml_path
                ELSE d.file_path END AS fp,
           NOT (d.status = 'completed' AND d.file_type = 'xbrl_zip' AND d.viewer_xml_path IS NULL) AS xml_source
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE f.fiscal_year >= 2015 AND f.is_final
      AND (f.ifrs_evidence IS NULL OR f.consolidation_evidence_detail IS NULL)
    ORDER BY f.rcept_no
""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    stat: Counter = Counter()
    with get_session() as s:
        if args.apply:
            s.execute(text("""CREATE TABLE IF NOT EXISTS public.filing_evidence_backfill_20261117 (
                rcept_no text, corp_code text, col text, new_value text, PRIMARY KEY (rcept_no, col))"""))
        rows = s.execute(_SQL).fetchall()
        print(f"대상 필링 {len(rows)}", flush=True)
        for i, r in enumerate(rows, 1):
            fp = on_disk_str(r.fp)
            if r.need_ifrs:
                ev, det = ie.resolve_filing_evidence(s, r.rcept_no, file_path=fp if r.xml_source else None)
                stat[("ifrs", ev)] += 1
                if ev and args.apply:
                    s.execute(text("UPDATE filings SET ifrs_evidence = :e, ifrs_evidence_detail = CAST(:d AS jsonb) "
                                   "WHERE rcept_no = :r AND ifrs_evidence IS NULL"),
                              {"e": ev, "d": _json(det), "r": r.rcept_no})
                    _log(s, r, "ifrs_evidence", ev)
            if r.need_cons:
                ev, det = ce.resolve_filing_evidence(s, r.rcept_no, file_path=fp)
                stat[("cons", ev)] += 1
                if ev and args.apply:
                    s.execute(text("UPDATE filings SET consolidation_evidence = :e, "
                                   "consolidation_evidence_detail = CAST(:d AS jsonb) "
                                   "WHERE rcept_no = :r AND consolidation_evidence_detail IS NULL"),
                              {"e": ev, "d": _json(det), "r": r.rcept_no})
                    _log(s, r, "consolidation_evidence", ev)
            if args.apply and i % 200 == 0:
                s.commit()
                print(f"  {i}/{len(rows)}", flush=True)
        if args.apply:
            s.commit()
    for k, v in sorted(stat.items(), key=lambda x: (x[0][0], -x[1])):
        print(k, v)
    print("applied" if args.apply else "dry run")


def _json(d) -> str | None:
    import json
    return json.dumps(d, ensure_ascii=False) if d else None


def _log(s, r, col: str, ev: str) -> None:
    s.execute(text("INSERT INTO public.filing_evidence_backfill_20261117 (rcept_no, corp_code, col, new_value) "
                   "VALUES (:r, :c, :col, :v) ON CONFLICT DO NOTHING"),
              {"r": r.rcept_no, "c": r.corp_code, "col": col, "v": ev})


if __name__ == "__main__":
    main()
