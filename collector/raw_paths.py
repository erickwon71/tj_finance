"""Resolve a raw_report path to the name it actually has on disk (Unicode normalization).

Why (2026-11-17): the company folders on the NAS (`raw_report` -> /Volumes/tj_finance_data, SMB) are
stored with NFD (decomposed) Hangul names, while the code builds and the DB stores NFC (composed)
names. Until macOS 27.2.1 the SMB client matched an NFC lookup to the NFD entry; after the update
it does so only briefly after a mount, then every NFC lookup of a Hangul folder fails
(FileNotFoundError) while the NFD name always works. APFS and the HFS SD mirror are normalization
insensitive, so the on-disk (NFD) spelling works on every volume.

`on_disk(path)` returns the path with every component replaced by the directory entry it matches
under NFC comparison when the given spelling is not found. It never invents a name: a component
with no matching entry leaves the path as given.
"""
from __future__ import annotations

import os
import time
import unicodedata
from pathlib import Path

_LIST_TTL_S = 300
_listing: dict[str, tuple[float, dict[str, str]]] = {}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _entries(directory: str) -> dict[str, str]:
    """NFC name -> on-disk name for one directory, cached for a few minutes."""
    now = time.monotonic()
    hit = _listing.get(directory)
    if hit and now - hit[0] < _LIST_TTL_S:
        return hit[1]
    try:
        names = os.listdir(directory)
    except OSError:
        names = []
    table = {_nfc(n): n for n in names}
    _listing[directory] = (now, table)
    return table


def clear_cache() -> None:
    _listing.clear()


def on_disk(path: str | os.PathLike) -> Path:
    """The same path spelled as on disk; the input unchanged when it exists or cannot be matched."""
    p = Path(path)
    if p.exists() or p.is_symlink():
        return p
    parts = p.parts
    cur = Path(parts[0])
    for i, part in enumerate(parts[1:], 1):
        cand = cur / part
        if cand.exists() or cand.is_symlink():
            cur = cand
            continue
        name = _entries(str(cur)).get(_nfc(part))
        if name is None:
            # Retry once with a fresh listing (a folder created since the listing was cached).
            _listing.pop(str(cur), None)
            name = _entries(str(cur)).get(_nfc(part))
        if name is None:
            return p
        cur = cur / name
    return cur


def on_disk_str(path: str | None) -> str | None:
    return None if path is None else str(on_disk(path))
