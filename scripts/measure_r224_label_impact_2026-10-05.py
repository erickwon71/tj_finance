#!/usr/bin/env python
"""R224 영향 측정 (READ-ONLY) — 고친 파서로 재추출하면 기존 report_lines/note_lines 라벨이 어떻게 바뀌나.

docs/PARSING_RULES.md R224. 연도별 층화 표본을 수정 코드(`extract_report_lines`)로 다시 뽑아
DB 의 (statement, basis, label_raw) 집합과 비교한다. 바뀐 라벨 중 '&'·'<'·'>'·'"' 를 포함하는
것을 R224 효과로 센다(그 밖의 차이는 9/17 이후 다른 규칙 변경분이라 따로 센다).

    python scripts/measure_r224_label_impact_2026-10-05.py --per-year 40 --workers 3 --sd-mirror
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from fin2.extract.report_lines import extract_report_lines

_SPECIAL = ("&", "<", '"')   # '>' is also the extractor's own path separator — not used


def _stripped(label: str) -> str:
    for ch in _SPECIAL:
        label = label.replace(ch, "")
    return label
_SAMPLE_SQL = """
    SELECT rcept_no, corp_code, fiscal_year, fiscal_period, file_path FROM (
        SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path,
               row_number() OVER (PARTITION BY f.fiscal_year ORDER BY md5(f.rcept_no)) rn
        FROM filings f JOIN download_tasks d USING (rcept_no)
        WHERE d.status = 'completed' AND d.file_type = 'xml' AND d.file_path IS NOT NULL
          AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
    ) x WHERE rn <= :n
"""


def _work(args):
    r, use_sd, notes = args
    p = Path(r["file_path"])
    if use_sd:
        p = BACKUP_ROOT / p.relative_to(_RAW_REPORT_SYMLINK)
    raw = p.read_bytes()
    has_cr = b"&cr;" in raw
    try:
        lines = extract_report_lines(str(p), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                                     report_fiscal_year=r["fiscal_year"],
                                     report_fiscal_period=r["fiscal_period"],
                                     include_notes=notes)
    except Exception as exc:  # noqa: BLE001
        return r["rcept_no"], has_cr, None, None, f"{type(exc).__name__}: {exc}"
    new = {(l.statement, l.basis, l.label_raw) for l in lines
           if l.statement != "note" and (l.col_index or 0) == 0}
    new_n = {(l.basis, l.label_raw) for l in lines if l.statement == "note"} if notes else None
    return r["rcept_no"], has_cr, new, new_n, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-year", type=int, default=40)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sd-mirror", action="store_true")
    ap.add_argument("--notes", action="store_true", help="also compare note_lines labels")
    args = ap.parse_args()
    with get_session() as s:
        rows = [dict(x) for x in s.execute(text(_SAMPLE_SQL), {"n": args.per_year}).mappings()]
    agg = Counter()
    examples = []
    with Pool(args.workers) as pool, get_session() as s:
        for rcept, has_cr, new, new_n, err in pool.imap_unordered(
                _work, [(r, args.sd_mirror, args.notes) for r in rows], chunksize=2):
            agg["filings"] += 1
            agg["with_cr"] += has_cr
            if err:
                agg["error"] += 1
                continue
            old = {(a, b, c) for a, b, c in s.execute(text(
                "SELECT DISTINCT statement, basis, label_raw FROM report_lines WHERE rcept_no=:r"),
                {"r": rcept})}
            # R224 signature: the new label minus the restored characters is an old label
            old_labels = {x[2] for x in old}
            added = {x for x in new - old if any(ch in x[2] for ch in _SPECIAL)
                     and _stripped(x[2]) in old_labels}
            if added:
                agg["filings_body_label_changed_r224"] += 1
                agg["body_labels_changed_r224"] += len(added)
                if len(examples) < 25:
                    examples.append((rcept, sorted(x[2] for x in added)[:4]))
            if new_n is not None:
                old_n = {(b, c) for b, c in s.execute(text(
                    "SELECT DISTINCT basis, label_raw FROM note_lines WHERE rcept_no=:r"),
                    {"r": rcept})}
                old_nl = {x[1] for x in old_n}
                added_n = {x for x in new_n - old_n if any(ch in x[1] for ch in _SPECIAL)
                           and _stripped(x[1]) in old_nl}
                if added_n:
                    agg["filings_note_label_changed_r224"] += 1
                    agg["note_labels_changed_r224"] += len(added_n)
    print(dict(agg))
    for e in examples:
        print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
