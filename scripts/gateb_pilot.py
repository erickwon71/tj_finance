"""
Gate B 신뢰성 파일럿 (PRD 04 §9.1) — 생산 감사 아님.

골든/표본 corp 의 최근 FY std_v2 행을 원본 보고서 face 표(독립 재추출)와 대조해
  (1) 독립 reader 가 보고서 진실표를 올바로 읽는지 (reader 신뢰성)
  (2) std_v2 최종값이 보고서와 일치하는지 (첫 mismatch 표면화)
를 눈으로 검증한다.

usage: python scripts/gateb_pilot.py [corp_code ...] [--years N]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import (
    read_report_face_xbrl, audit_std_row, ANCHOR_FIELDS,
)

GOLDEN = ["00162416", "01275665", "01492651", "01367586"]  # 한양증권·리메드·큐로셀·지아이텍


def file_for(session, rcept):
    if not rcept:
        return None
    r = session.execute(text("""
        SELECT file_path FROM download_tasks
        WHERE rcept_no=:r AND file_type='xml' AND status='completed' AND file_path IS NOT NULL
        LIMIT 1
    """), {"r": rcept}).fetchone()
    return r.file_path if r else None


def audit_corp(session, corp, years):
    rows = session.execute(text("""
        SELECT * FROM std_financials_v2
        WHERE corp_code=:c AND version=1 AND fiscal_period='FY' AND NOT COALESCE(is_stub,false)
        ORDER BY fiscal_year DESC, statement_type
        LIMIT :lim
    """), {"c": corp, "lim": years * 2}).fetchall()
    if not rows:
        print(f"  {corp}: std_v2 FY 없음")
        return (0, 0, 0)
    name = session.execute(text("SELECT corp_name FROM corporations WHERE corp_code=:c"), {"c": corp}).scalar()
    print(f"\n=== {name} ({corp}) ===")
    tot_pass = tot_fail = tot_pend = 0
    row_stat = {"pass": 0, "fail": 0, "pending": 0}
    face_cache: dict[str, list] = {}

    def face_of(rc):
        if not rc:
            return []
        if rc not in face_cache:
            fp = file_for(session, rc)
            face_cache[rc] = read_report_face_xbrl(fp) if fp else []
        return face_cache[rc]

    for row in rows:
        d = dict(row._mapping)
        basis = d["statement_type"]
        rules = d.get("applied_rules") or []
        is_comp = "comparative_fallback" in rules
        ra = audit_std_row(
            d, basis=basis,
            bs_face=face_of(d.get("bs_rcept")),
            is_face=face_of(d.get("is_rcept")),
            cf_face=face_of(d.get("cf_rcept")),
            is_comparative=is_comp,
        )
        row_stat[ra.status] += 1
        tot_pass += ra.n_pass; tot_fail += ra.n_fail; tot_pend += ra.n_pending
        flag = {"pass": "✅", "fail": "❌", "pending": "⏳"}[ra.status]
        extra = f" FAIL={ra.fail_fields}" if ra.fail_fields else ""
        print(f"  {flag} FY{d['fiscal_year']} {basis:12s} "
              f"[pass {ra.n_pass} / fail {ra.n_fail} / pending {ra.n_pending}]{extra}")
        for fa in ra.fields:
            if fa.reason in ("VALUE_DIFF",):  # 진짜 오류만 상세
                anc = "*" if fa.field in ANCHOR_FIELDS else " "
                print(f"      XX {anc}{fa.field:18s} db={fa.db_amount_won:>18,} "
                      f"report≈{fa.report_value_won}")
    print(f"   rows: pass {row_stat['pass']} / fail {row_stat['fail']} / pending {row_stat['pending']}")
    return (tot_pass, tot_fail, tot_pend)


def main():
    years = 2
    argv = sys.argv[1:]
    corps = []
    i = 0
    while i < len(argv):
        if argv[i] == "--years":
            years = int(argv[i + 1]); i += 2; continue
        corps.append(argv[i]); i += 1
    corps = corps or GOLDEN
    with get_session() as s:
        P = F = U = 0
        for c in corps:
            p, f, u = audit_corp(s, c, years)
            P += p; F += f; U += u
    denom = P + F
    rate = f"{P/denom*100:.1f}%" if denom else "n/a"
    print(f"\n── 필드 합계: PASS {P} · FAIL(VALUE_DIFF) {F} · PENDING {U} "
          f"(in-scope 일치율 = {rate})")


if __name__ == "__main__":
    main()
