"""잔여 LABEL_UNMATCHED(새 reader 기준) 한 필드의 케이스를 덤프 — applied_rules + is_face 라인.

usage: python scripts/gateb_probe_residual.py FIELD [--limit N] [--fy-min Y]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import (
    read_report_face_tracked, audit_std_row, STD_FIELD_CANONICAL, _statement_face,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("field")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--fy-min", type=int, default=2015)
    ap.add_argument("--dump", type=int, default=12, help="상세 덤프 케이스 수")
    args = ap.parse_args()
    field = args.field
    canon = STD_FIELD_CANONICAL[field]

    with get_session() as s:
        rows = s.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, statement_type
            FROM face_audit WHERE gate_status='pending' AND pending_detail ? 'LABEL_UNMATCHED'
              AND fiscal_year >= :fymin
            ORDER BY random() LIMIT :lim
        """), {"fymin": args.fy_min, "lim": args.limit}).fetchall()

        rules_cnt = Counter()
        sector = Counter()
        dumped = 0
        residual = 0
        for (corp, fy, fp, st) in rows:
            d = s.execute(text("""SELECT * FROM std_financials_v2 WHERE corp_code=:c
                AND fiscal_year=:y AND fiscal_period=:p AND statement_type=:st
                AND version=1 AND NOT COALESCE(is_stub,false)"""),
                {"c": corp, "y": fy, "p": fp, "st": st}).fetchone()
            if d is None:
                continue
            dm = dict(d._mapping)
            if dm.get(field) is None:
                continue
            rcepts = {k: dm.get(k) for k in ("bs_rcept", "is_rcept", "cf_rcept")}
            fp_map = {}
            for rc in set(v for v in rcepts.values() if v):
                fr = s.execute(text("""SELECT file_path FROM download_tasks WHERE rcept_no=:rc
                    AND file_type='xml' AND status='completed' AND file_path IS NOT NULL LIMIT 1"""),
                    {"rc": rc}).fetchone()
                fp_map[rc] = fr[0] if fr else None
            cache = {}
            def face_of(rc):
                if not rc: return []
                if rc not in cache:
                    fpath = fp_map.get(rc)
                    try: ls, _ = read_report_face_tracked(fpath) if fpath else ([], None)
                    except (FileNotFoundError, OSError): ls = []
                    cache[rc] = ls
                return cache[rc]
            bs_f, is_f, cf_f = face_of(rcepts["bs_rcept"]), face_of(rcepts["is_rcept"]), face_of(rcepts["cf_rcept"])
            ra = audit_std_row(dm, basis=st, bs_face=bs_f, is_face=is_f, cf_face=cf_f, is_comparative=False)
            fa = next((f for f in ra.fields if f.field == field and f.reason == "LABEL_UNMATCHED"), None)
            if fa is None:
                continue
            residual += 1
            rules = dm.get("applied_rules") or []
            for r in rules: rules_cnt[r] += 1
            comp = s.execute(text("SELECT corp_name FROM corporations WHERE corp_code=:c"), {"c": corp}).scalar()
            val = dm[field]
            face = _statement_face(field, bs_f, is_f, cf_f)
            # 같은 statement face 의 모든 라인 중 값이 가까운 것들
            near = sorted(face, key=lambda ln: abs((ln.amount_won or 0) - val))[:4]
            if dumped < args.dump:
                dumped += 1
                print(f"\n[{corp} {comp}] {fy} {fp} {st} {field}={val}")
                print(f"   rules={rules}")
                for ln in near:
                    flag = "  <==값일치" if ln.amount_won in (val, -val) else ""
                    print(f"   face canon={ln.canonical} basis={ln.basis} won={ln.amount_won} label={ln.label!r}{flag}")

    print(f"\n=== 잔여 {residual} (필드={field}) applied_rules 빈도 ===")
    for k, v in rules_cnt.most_common():
        print(f"  {k:30} {v}")


if __name__ == "__main__":
    main()
