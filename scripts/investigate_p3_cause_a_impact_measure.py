"""R35 적용 후 실제 impact 측정 — 668건(원인 A 잔여, R34 이후) 각각을 다시
audit_std_row() 로 재판정해서 몇 건이 pass 로 회복되는지 직접 센다(DB 커밋 없음, 읽기전용).

용법: .venv/bin/python scripts/investigate_p3_cause_a_impact_measure.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import read_report_face_tracked, audit_std_row

session_cm = get_session()
session = session_cm.__enter__()

violated = session.execute(text("""
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type
    FROM face_audit_snap_20260819 s
    JOIN face_audit f
      ON f.corp_code=s.corp_code AND f.fiscal_year=s.fiscal_year AND f.fiscal_period=s.fiscal_period
     AND f.statement_type=s.statement_type AND f.is_stub=s.is_stub AND f.source_version=s.source_version
    WHERE s.gate_status='pass' AND f.gate_status IN ('fail_a','fail_b','pending')
    ORDER BY 1,2,3,4
""")).fetchall()

print(f"대상 (corp,fy,period,statement_type) 행: {len(violated)}건")


def file_path_map(rcepts):
    if not rcepts:
        return {}
    rows = session.execute(text("""
        SELECT rcept_no, file_path, file_type FROM download_tasks
        WHERE rcept_no = ANY(:rs) AND file_type IN ('xml','pdf') AND status='completed'
          AND file_path IS NOT NULL
    """), {"rs": list(rcepts)}).fetchall()
    fmap = {}
    for r in rows:
        if r.file_type == "xml" or r.rcept_no not in fmap:
            fmap[r.rcept_no] = r.file_path
    return fmap


status_counter = Counter()
still_bad: list[tuple] = []
face_cache: dict[str, list] = {}

for corp, fy, period, stype in violated:
    d_row = session.execute(text("""
        SELECT * FROM std_financials_v3
        WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:p AND statement_type=:st
    """), {"c": corp, "fy": fy, "p": period, "st": stype}).fetchone()
    if d_row is None:
        status_counter["ROW_MISSING_IN_V3"] += 1
        continue
    d = dict(d_row._mapping)
    rc = dict(d.get("source_rcepts") or {})
    rcepts = [v for v in rc.values() if v]
    fpmap = file_path_map(rcepts)

    def face_of(rcept):
        if not rcept:
            return []
        if rcept not in face_cache:
            fp = fpmap.get(rcept)
            try:
                lines, _track = read_report_face_tracked(fp, all_cols=False) if fp else ([], None)
            except (FileNotFoundError, OSError):
                lines = []
            face_cache[rcept] = lines
        return face_cache[rcept]

    ra = audit_std_row(
        d, basis=stype,
        bs_face=face_of(rc.get("BS")), is_face=face_of(rc.get("IS")), cf_face=face_of(rc.get("CF")),
        is_comparative=False,
    )
    status_counter[ra.status] += 1
    if ra.status != "pass":
        still_bad.append((corp, fy, period, stype, ra.status,
                          [f.reason for f in ra.fields if f.reason and f.reason != "VALUE_DIFF" and not f.match]))

print("\n=== 재판정 결과(row status) ===")
for k, v in status_counter.most_common():
    print(f"{v:5d}  {k}")

print(f"\n=== pass 미회복 {len(still_bad)}건 중 회사별 분포(상위 20) ===")
corp_counter = Counter(row[0] for row in still_bad)
for corp, n in corp_counter.most_common(20):
    print(f"{n:5d}  {corp}")
