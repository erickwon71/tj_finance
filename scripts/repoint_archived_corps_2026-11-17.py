"""Repoint download_tasks.file_path of archived (delisted) corps to their archive folder.

collector/delisting_archive._repoint_download_tasks compared the NFD folder name from the listing
with the NFC stored path, so it never matched: 10 corps archived on 2026-10-26 kept 979 paths under
raw_report that no longer exist. The path below the company folder is kept; the company folder part
is replaced by corporations.archive_path. Old values go to public.raw_path_backup_20261117.

Usage: python scripts/repoint_archived_corps_2026-11-17.py [--apply]
"""
from __future__ import annotations

import argparse
import os
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402

RAW = "/Users/taejin/Project/tj_finance/raw_report/"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    with get_session() as s:
        rows = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, c.archive_path
            FROM download_tasks dt JOIN filings f USING (rcept_no) JOIN corporations c ON c.corp_code = f.corp_code
            WHERE NOT c.is_active AND c.archive_path IS NOT NULL AND dt.file_path LIKE :raw""" ),
            {"raw": RAW + "%"}).fetchall()
        changes, missing = [], 0
        for rcept, fp, arch in rows:
            rest = unicodedata.normalize("NFC", fp)[len(RAW):].split("/", 2)   # market, company, rest
            new = arch.rstrip("/") + "/" + rest[2]
            if os.path.exists(new):
                changes.append({"k": rcept, "old": fp, "new": new})
            else:
                missing += 1
        print(f"filings {len(rows)} · repoint {len(changes)} · new path missing {missing}")
        if args.apply and changes:
            s.execute(text("""INSERT INTO public.raw_path_backup_20261117 (tbl, key, col, old_value, new_value)
                              VALUES ('download_tasks', :k, 'file_path', :old, :new)
                              ON CONFLICT (tbl, key, col) DO UPDATE SET new_value = EXCLUDED.new_value"""), changes)
            s.execute(text("UPDATE download_tasks SET file_path = :new WHERE rcept_no = :k AND file_path = :old"), changes)
            s.commit()
            print("applied")


if __name__ == "__main__":
    main()
