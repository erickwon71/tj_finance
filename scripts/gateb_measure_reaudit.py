"""현재 pending 행을 새 reader/audit 로직으로 재감사(메모리)해 status 전이를 측정(DB 미반영).

usage: python scripts/gateb_measure_reaudit.py [--reason R] [--limit N] [--fy-min Y]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import read_report_face_tracked, audit_std_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default=None, help="pending_detail 키 필터(예 LABEL_UNMATCHED)")
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--fy-min", type=int, default=2015)
    args = ap.parse_args()

    with get_session() as s:
        q = """
            SELECT corp_code, fiscal_year, fiscal_period, statement_type
            FROM face_audit
            WHERE gate_status='pending' AND fiscal_year >= :fymin
        """
        params = {"fymin": args.fy_min, "lim": args.limit}
        if args.reason:
            q += " AND pending_detail ? :reason"
            params["reason"] = args.reason
        q += " ORDER BY random() LIMIT :lim"
        rows = s.execute(text(q), params).fetchall()
        print(f"재감사 측정 대상 {len(rows)}행 (reason={args.reason}, fy>={args.fy_min})")

        trans = Counter()       # new status
        new_reason = Counter()  # 잔여 pending 사유
        for (corp, fy, fp, stmt_type) in rows:
            d = s.execute(text("""
                SELECT * FROM std_financials_v2
                WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
                  AND statement_type=:st AND version=1 AND NOT COALESCE(is_stub,false)
            """), {"c": corp, "y": fy, "p": fp, "st": stmt_type}).fetchone()
            if d is None:
                continue
            dm = dict(d._mapping)
            rcepts = {k: dm.get(k) for k in ("bs_rcept", "is_rcept", "cf_rcept")}
            fp_map = {}
            for rc in set(v for v in rcepts.values() if v):
                fr = s.execute(text("""
                    SELECT file_path FROM download_tasks WHERE rcept_no=:rc
                      AND file_type='xml' AND status='completed' AND file_path IS NOT NULL LIMIT 1
                """), {"rc": rc}).fetchone()
                fp_map[rc] = fr[0] if fr else None
            cache = {}
            def face_of(rc, all_cols=False):
                if not rc:
                    return []
                k = (rc, all_cols)
                if k not in cache:
                    fpath = fp_map.get(rc)
                    try:
                        ls, _ = read_report_face_tracked(fpath, all_cols=all_cols) if fpath else ([], None)
                    except (FileNotFoundError, OSError):
                        ls = []
                    cache[k] = ls
                return cache[k]
            rules = dm.get("applied_rules") or []
            is_comp = "comparative_fallback" in rules
            ra = audit_std_row(
                dm, basis=stmt_type,
                bs_face=face_of(rcepts["bs_rcept"], all_cols=is_comp),
                is_face=face_of(rcepts["is_rcept"], all_cols=is_comp),
                cf_face=face_of(rcepts["cf_rcept"], all_cols=is_comp),
                is_comparative=is_comp,
            )
            trans[ra.status] += 1
            if ra.status == "pending":
                for f in ra.fields:
                    if f.reason and f.reason != "VALUE_DIFF":
                        new_reason[f.reason] += 1
            elif ra.status == "fail":
                new_reason["__FAIL__:" + ",".join(ra.fail_fields)] += 1

    print("\n=== 재감사 후 status ===")
    for k, v in trans.most_common():
        print(f"  {k:10} {v}")
    print("\n=== 잔여 pending 사유(필드합) ===")
    for k, v in new_reason.most_common(15):
        print(f"  {k:30} {v}")


if __name__ == "__main__":
    main()
