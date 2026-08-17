"""Equivalence gate for ③ Fix 2 — shared parsed tree in the Gate B face reader.

Fix 2 makes read_report_face_tracked() parse the XML once and hand the same tree to both
read_report_face_xbrl() and read_report_face_text(), instead of each parsing the file
itself (1.90 parses per filing; 76% of parse cost is sanitize_dart_xml — design doc B2).

Both readers only READ the tree, so sharing must be a no-op. This proves it: for every
sampled filing, compare (track, [FaceLine...]) produced by the shared-tree path against
the original per-reader-parse path (still reachable — the `root` parameters default to
None, which restores the old behavior exactly).

Pass criterion: 0 differing filings.

usage:
  python scripts/verify_face_reader_root_reuse_2026-08-17.py --corps 00111722,00101044
  python scripts/verify_face_reader_root_reuse_2026-08-17.py --sample 120
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import astuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text                       # noqa: E402
from collector.db import get_session              # noqa: E402
from fin2.audit import face_audit as fa           # noqa: E402


def legacy_tracked(file_path):
    """read_report_face_tracked() as it behaved BEFORE Fix 2 — every reader parses the
    file itself. Reproduced by simply leaving `root` unset on each call."""
    if str(file_path).lower().endswith(".pdf"):
        lines = fa.read_report_face_pdf(file_path)
        return (lines, "C") if lines else ([], None)
    lines = fa.read_report_face_xbrl(file_path)          # own parse
    if lines:
        lines = fa._supplement_with_text(lines, file_path)   # own parse
        return lines, "A"
    lines = fa.read_report_face_text(file_path)          # own parse
    if lines:
        return lines, "B"
    return [], None


def key(lines):
    return [astuple(ln) for ln in lines]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="쉼표구분 corp_code")
    ap.add_argument("--sample", type=int, default=0, help="무작위 파일 N건")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    with get_session() as s:
        if a.corps:
            corps = a.corps.split(",")
            rows = s.execute(text("""
                SELECT DISTINCT dt.file_path
                FROM std_financials_v3 v3,
                     LATERAL jsonb_each_text(v3.source_rcepts) AS kv(k, v)
                JOIN download_tasks dt ON dt.rcept_no = kv.v AND dt.status='completed'
                                      AND dt.file_type='xml' AND dt.file_path IS NOT NULL
                WHERE v3.corp_code = ANY(:cs)
            """), {"cs": corps}).fetchall()
        else:
            rows = s.execute(text("""
                SELECT DISTINCT dt.file_path
                FROM std_financials_v3 v3,
                     LATERAL jsonb_each_text(v3.source_rcepts) AS kv(k, v)
                JOIN download_tasks dt ON dt.rcept_no = kv.v AND dt.status='completed'
                                      AND dt.file_type='xml' AND dt.file_path IS NOT NULL
                LIMIT 20000
            """)).fetchall()
    files = [r[0] for r in rows]
    if a.sample and len(files) > a.sample:
        random.seed(a.seed)
        files = random.sample(files, a.sample)
    print(f"대상 파일 {len(files)}건")

    diffs, errs, n = [], 0, 0
    for fp in files:
        try:
            new_lines, new_tr = fa.read_report_face_tracked(fp)      # shared tree
            old_lines, old_tr = legacy_tracked(fp)                   # per-reader parse
        except (FileNotFoundError, OSError):
            errs += 1
            continue
        n += 1
        if new_tr != old_tr or key(new_lines) != key(old_lines):
            diffs.append((fp, old_tr, new_tr, len(old_lines), len(new_lines)))

    print(f"\n── 대조 {n}건 (파일없음 {errs}) ──")
    if diffs:
        print(f"❌ 불일치 {len(diffs)}건 — Fix 2 철회")
        for d in diffs[:10]:
            print("   ", d)
        sys.exit(1)
    print("✅ 불일치 0건 — track/FaceLine 완전 동일")


if __name__ == "__main__":
    main()
