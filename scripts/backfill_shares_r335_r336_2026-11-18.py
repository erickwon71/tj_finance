#!/usr/bin/env python
"""R335 / R336 backfill — re-read the share table (fin2/extract/shares.py) of the filings whose stored
counts are suspect and store the new reading when it differs.

Targets (layer 2 `report_shares_outstanding`):
  * the share count differs from the KRX listed count on the base date (or KRX has no row), and
  * the table identity Ⅳ = Ⅴ + Ⅵ is broken (×1,000 mixed rows such as NAVER 2016).
Rows that already equal the KRX listed count are not targets (a 3,000-row sample of them did not change).

Old values are kept in public.report_shares_r335_backup_20261118 (rcept_no, old/new columns).

    python scripts/backfill_shares_r335_r336_2026-11-18.py            # dry-run
    python scripts/backfill_shares_r335_r336_2026-11-18.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.shares import extract_share_counts  # noqa: E402
from fin2.extract.shares_transcribe import store_report_shares  # noqa: E402
from fin2.verification.ops import _sd_path  # noqa: E402

_TARGETS = """
WITH r AS (
  SELECT r.rcept_no, r.corp_code, r.fiscal_year, r.fiscal_period, r.as_of_date,
         r.shares_out, r.treasury_shares, r.float_shares, dt.file_path,
         (SELECT sp.list_shares FROM stock_prices sp
           WHERE sp.stock_code = c.stock_code AND sp.trade_date <= r.as_of_date
             AND sp.trade_date > r.as_of_date - 10 AND sp.list_shares IS NOT NULL
           ORDER BY sp.trade_date DESC LIMIT 1) AS k
  FROM report_shares_outstanding r
  JOIN corporations c USING (corp_code)
  JOIN download_tasks dt ON dt.rcept_no = r.rcept_no AND dt.file_type = 'xml' AND dt.status = 'completed')
SELECT * FROM r
WHERE k IS NULL OR shares_out <> k
   OR (float_shares IS NOT NULL AND float_shares + coalesce(treasury_shares, 0) <> shares_out)
ORDER BY rcept_no
"""

_BACKUP = """
CREATE TABLE IF NOT EXISTS public.report_shares_r335_backup_20261118 (
  rcept_no varchar(14) PRIMARY KEY, corp_code varchar(8),
  old_shares_out bigint, old_treasury bigint, old_float bigint, old_source_ref varchar(40),
  new_shares_out bigint, new_treasury bigint, new_float bigint, new_source_ref varchar(40),
  krx_list_shares bigint, logged_at timestamp DEFAULT now())
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(_TARGETS)).fetchall()
        print(f"targets {len(rows)}", flush=True)
        if args.apply:
            s.execute(text(_BACKUP))
        changed, corps, errors = 0, set(), 0
        for i, r in enumerate(rows):
            try:
                f = extract_share_counts(_sd_path(r.file_path))
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                errors += 1
                print(f"ERR {r.rcept_no} {type(exc).__name__}: {exc}")
                continue
            if not f:
                continue
            new = (f["issued"], f["treasury"], f["float"])
            old = (r.shares_out, r.treasury_shares, r.float_shares)
            if new == old:
                continue
            changed += 1
            corps.add(r.corp_code)
            print(f"{r.rcept_no} {r.corp_code} {old} -> {new} krx={r.k}")
            if args.apply:
                old_src = s.execute(text(
                    "SELECT source_ref FROM report_shares_outstanding WHERE rcept_no = :r"),
                    {"r": r.rcept_no}).scalar()
                s.execute(text("""
                    INSERT INTO public.report_shares_r335_backup_20261118
                      (rcept_no, corp_code, old_shares_out, old_treasury, old_float, old_source_ref,
                       new_shares_out, new_treasury, new_float, new_source_ref, krx_list_shares)
                    VALUES (:r, :c, :o1, :o2, :o3, :os, :n1, :n2, :n3, :ns, :k)
                    ON CONFLICT (rcept_no) DO NOTHING"""),
                    {"r": r.rcept_no, "c": r.corp_code, "o1": old[0], "o2": old[1], "o3": old[2],
                     "os": old_src, "n1": new[0], "n2": new[1], "n3": new[2],
                     "ns": f["issued_label"], "k": r.k})
                store_report_shares(s, r.rcept_no, r.corp_code, r.fiscal_year, r.fiscal_period,
                                    f["issued"], r.as_of_date, f["issued_label"],
                                    treasury_shares=f["treasury"], float_shares=f["float"])
            if i % 1000 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
        if args.apply:
            s.commit()
        print(f"changed {changed} corps {len(corps)} errors {errors}")
        print("CORPS " + ",".join(sorted(corps)))


if __name__ == "__main__":
    main()
