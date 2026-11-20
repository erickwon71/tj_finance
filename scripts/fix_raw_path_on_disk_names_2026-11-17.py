"""Rewrite stored raw_report paths to the folder names they have on disk (NFD Hangul on the NAS).

Why: after macOS 27.2.1 an NFC lookup of an NFD-named Hangul folder on the NAS (SMB) fails, so
the NFC paths stored in the DB stopped opening (collector/raw_paths.py). Only the company-folder
component carries Hangul, so each stored path is rewritten by replacing that component with the
directory entry whose NFC form matches it. Paths whose folder is not found are left as they are.

Columns: download_tasks.file_path / viewer_xml_path / orig_pdf_path, corporations.archive_path.
--apply first copies the old values into public.raw_path_backup_20261117 (key, column, old value),
so the change can be undone with one UPDATE ... FROM.

Usage:
    python scripts/fix_raw_path_on_disk_names_2026-11-17.py            # dry run: counts only
    python scripts/fix_raw_path_on_disk_names_2026-11-17.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402

_listings: dict[str, dict[str, str]] = {}


def _entries(directory: str) -> dict[str, str]:
    if directory not in _listings:
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        _listings[directory] = {unicodedata.normalize("NFC", n): n for n in names}
    return _listings[directory]


def on_disk_name(path: str) -> str | None:
    """The path with its Hangul components spelled as on disk; None when a component is not found."""
    parts = Path(path).parts
    out = Path(parts[0])
    for part in parts[1:]:
        if part.isascii():
            out = out / part
            continue
        name = _entries(str(out)).get(unicodedata.normalize("NFC", part))
        if name is None:
            return None
        out = out / name
    return str(out)


_TARGETS = [
    ("download_tasks", "rcept_no", "file_path"),
    ("download_tasks", "rcept_no", "viewer_xml_path"),
    ("download_tasks", "rcept_no", "orig_pdf_path"),
    ("corporations", "corp_code", "archive_path"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # R357 (2026-11-20): a second run must not hit ON CONFLICT DO NOTHING on keys backed up before
    ap.add_argument("--backup-table", default="raw_path_backup_20261117")
    args = ap.parse_args()
    bt = args.backup_table
    if not bt.replace("_", "").isalnum():
        raise SystemExit(f"bad --backup-table: {bt}")

    with get_session() as s:
        if args.apply:
            s.execute(text(f"""CREATE TABLE IF NOT EXISTS public.{bt} (
                tbl text, key text, col text, old_value text, new_value text,
                PRIMARY KEY (tbl, key, col))"""))
        for tbl, key, col in _TARGETS:
            rows = s.execute(text(f"SELECT {key}, {col} FROM {tbl} WHERE {col} IS NOT NULL")).fetchall()
            stat: Counter = Counter()
            changes = []
            for k, old in rows:
                if old.isascii():
                    stat["ascii"] += 1
                    continue
                new = on_disk_name(old)
                if new is None:
                    stat["not_found"] += 1
                elif new == old:
                    stat["same"] += 1
                else:
                    stat["change"] += 1
                    changes.append({"k": k, "old": old, "new": new})
            print(f"{tbl}.{col}: {dict(stat)}", flush=True)
            if args.apply and changes:
                s.execute(text(f"""INSERT INTO public.{bt} (tbl, key, col, old_value, new_value)
                                  VALUES (:t, :k, :c, :old, :new)
                                  ON CONFLICT (tbl, key, col) DO NOTHING"""),
                          [{"t": tbl, "c": col, **c} for c in changes])
                s.execute(text(f"UPDATE {tbl} SET {col} = :new WHERE {key} = :k AND {col} = :old"), changes)
        if args.apply:
            s.commit()
            print("applied")


if __name__ == "__main__":
    main()
