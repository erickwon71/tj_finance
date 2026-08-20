"""P3-1 후속 — '원인 A'(689건 단조성 위반 중 R34 depth-bug 30건을 뺀 나머지, 현재 668건)의
실제 field-level 원인을 census 한다.

face_audit/face_audit_snap_20260819 에는 (LABEL_UNMATCHED/SOURCE_NOT_TRACK_A) 개수만
남아있고 어떤 field 인지는 없다 — audit_std_row() 를 실제로 재실행해서 field 단위로 분류한다.

용법: .venv/bin/python scripts/investigate_p3_cause_a_field_census.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import read_report_face_tracked, audit_std_row, STD_FIELD_CANONICAL

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


field_reason_counter = Counter()
row_examples: dict[str, list] = {}
face_cache: dict[str, list] = {}

for corp, fy, period, stype in violated:
    d_row = session.execute(text("""
        SELECT * FROM std_financials_v3
        WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:p AND statement_type=:st
    """), {"c": corp, "fy": fy, "p": period, "st": stype}).fetchone()
    if d_row is None:
        field_reason_counter["ROW_MISSING_IN_V3"] += 1
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
    for f in ra.fields:
        if f.reason in ("LABEL_UNMATCHED", "SOURCE_NOT_TRACK_A"):
            key = f"{f.reason}:{f.field}"
            field_reason_counter[key] += 1
            if len(row_examples.get(key, [])) < 5:
                row_examples.setdefault(key, []).append((corp, fy, period, stype, f.canonical, f.db_amount_won))

print("\n=== field 단위 분포 (상위 40) ===")
for key, n in field_reason_counter.most_common(40):
    print(f"{n:5d}  {key}")

print("\n=== 상위 10개 field 의 실제 예시 5건씩 ===")
for key, _ in field_reason_counter.most_common(10):
    print(f"\n-- {key} --")
    for ex in row_examples.get(key, []):
        print("  ", ex)
