"""잔여 COMPARATIVE_ROW 케이스 덤프 — std 비교행 값 vs 그 보고서 all_cols face 라인."""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import (
    read_report_face_tracked, audit_std_row, STD_FIELD_CANONICAL, _statement_face,
)

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 120
DUMP = int(sys.argv[2]) if len(sys.argv) > 2 else 12

with get_session() as s:
    rows = s.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type FROM face_audit
        WHERE gate_status='pending' AND pending_detail ? 'COMPARATIVE_ROW' AND fiscal_year>=2015
        ORDER BY random() LIMIT :lim"""), {"lim": LIMIT}).fetchall()
    fail_field = Counter(); dumped = 0; resid = 0; face_empty = 0
    for (corp, fy, fp, st) in rows:
        d = s.execute(text("""SELECT * FROM std_financials_v2 WHERE corp_code=:c AND fiscal_year=:y
            AND fiscal_period=:p AND statement_type=:st AND version=1 AND NOT COALESCE(is_stub,false)"""),
            {"c": corp, "y": fy, "p": fp, "st": st}).fetchone()
        if d is None: continue
        dm = dict(d._mapping)
        rcepts = {k: dm.get(k) for k in ("bs_rcept", "is_rcept", "cf_rcept")}
        fp_map = {}
        for rc in set(v for v in rcepts.values() if v):
            fr = s.execute(text("""SELECT file_path FROM download_tasks WHERE rcept_no=:rc
                AND file_type='xml' AND status='completed' AND file_path IS NOT NULL LIMIT 1"""), {"rc": rc}).fetchone()
            fp_map[rc] = fr[0] if fr else None
        cache = {}
        def face_of(rc):
            if not rc: return []
            if rc not in cache:
                fpath = fp_map.get(rc)
                try: ls, _ = read_report_face_tracked(fpath, all_cols=True) if fpath else ([], None)
                except (FileNotFoundError, OSError): ls = []
                cache[rc] = ls
            return cache[rc]
        bs_f, is_f, cf_f = face_of(rcepts["bs_rcept"]), face_of(rcepts["is_rcept"]), face_of(rcepts["cf_rcept"])
        ra = audit_std_row(dm, basis=st, bs_face=bs_f, is_face=is_f, cf_face=cf_f, is_comparative=True)
        bad = [f for f in ra.fields if f.reason == "COMPARATIVE_ROW"]
        if not bad: continue
        resid += 1
        for f in bad: fail_field[f.field] += 1
        if dumped < DUMP:
            dumped += 1
            print(f"\n[{corp}] {fy} {fp} {st}  rcepts bs={rcepts['bs_rcept']} is={rcepts['is_rcept']} cf={rcepts['cf_rcept']}")
            print(f"   rules={dm.get('applied_rules')}")
            for f in bad[:4]:
                face = _statement_face(f.field, bs_f, is_f, cf_f)
                cands = [ln.amount_won for ln in face if ln.canonical == f.canonical]
                if not cands: face_empty += 1
                print(f"   {f.field}={f.db_amount_won} canon={f.canonical}  face_cands({len(cands)})={cands[:6]}")

print(f"\n=== 잔여 {resid}행, 필드별 ===")
for k, v in fail_field.most_common(): print(f"  {k:22} {v}")
