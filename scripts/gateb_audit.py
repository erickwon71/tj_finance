"""
Gate B 생산 감사 러너 — std_v2 행을 원본 보고서 face 표와 대조해 face_audit 대장 적재.

각 (corp,fy,fp,basis) 행을 audit_std_row 로 판정 → face_audit upsert.
status: pass(promote 가능) / fail(값불일치, 차단) / pending(범위밖).

대량 = XML 파일 다수 open → **장시간**(사용자 실행 권장). 소표본은 --corps/--limit/--sample.

usage:
  python scripts/gateb_audit.py --corps 00000000:00200000   # corp_code 범위
  python scripts/gateb_audit.py --sample 50                 # 무작위 50사
  python scripts/gateb_audit.py --corp 00162416             # 단일
  옵션: --fy-min 2015 --recheck --no-commit
"""
import argparse
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from collector.db import get_session, engine
from collector.models import FaceAudit, Base
from fin2.audit.face_audit import read_report_face_xbrl, audit_std_row

READER_VERSION = "xbrl-col0-v1"


def ensure_table():
    Base.metadata.create_all(engine, tables=[FaceAudit.__table__], checkfirst=True)


def file_path_map(session, rcepts):
    """rcept_no 집합 → file_path (xml, completed)."""
    if not rcepts:
        return {}
    rows = session.execute(text("""
        SELECT rcept_no, file_path FROM download_tasks
        WHERE rcept_no = ANY(:rs) AND file_type='xml' AND status='completed'
          AND file_path IS NOT NULL
    """), {"rs": list(rcepts)}).fetchall()
    return {r.rcept_no: r.file_path for r in rows}


def select_corps(session, args):
    if args.corp:
        return [args.corp]
    q = "SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=1"
    params = {}
    if args.corps:
        lo, hi = args.corps.split(":")
        q += " AND corp_code >= :lo AND corp_code < :hi"
        params = {"lo": lo, "hi": hi}
    q += " ORDER BY corp_code"
    corps = [r.corp_code for r in session.execute(text(q), params)]
    if args.sample:
        random.seed(args.seed)
        corps = random.sample(corps, min(args.sample, len(corps)))
    return corps


def audit_corp(session, corp, args, agg):
    rows = session.execute(text("""
        SELECT * FROM std_financials_v2
        WHERE corp_code=:c AND version=1 AND NOT COALESCE(is_stub,false)
          AND fiscal_year >= :fymin
        ORDER BY fiscal_year DESC
    """), {"c": corp, "fymin": args.fy_min}).fetchall()
    if not rows:
        return

    if not args.recheck:
        done = {(r.fiscal_year, r.fiscal_period, r.statement_type) for r in session.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type FROM face_audit
            WHERE corp_code=:c AND NOT COALESCE(is_stub,false)
        """), {"c": corp})}
    else:
        done = set()

    # 이 corp 의 모든 source rcept 파일을 1회씩 읽어 캐시
    rcepts = set()
    for r in rows:
        for k in ("bs_rcept", "is_rcept", "cf_rcept"):
            if getattr(r, k):
                rcepts.add(getattr(r, k))
    fpmap = file_path_map(session, rcepts)
    face_cache: dict[str, list] = {}

    def face_of(rc):
        if not rc:
            return []
        if rc not in face_cache:
            fp = fpmap.get(rc)
            face_cache[rc] = read_report_face_xbrl(fp) if fp else []
        return face_cache[rc]

    batch = []
    for r in rows:
        d = dict(r._mapping)
        key = (d["fiscal_year"], d["fiscal_period"], d["statement_type"])
        if key in done:
            continue
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
        agg["status"][ra.status] += 1
        agg["fld_pass"] += ra.n_pass; agg["fld_fail"] += ra.n_fail
        if ra.status == "fail":
            agg["fail_rows"].append((corp, key, ra.fail_fields))
        pend = Counter(f.reason for f in ra.fields if f.reason and f.reason != "VALUE_DIFF")
        batch.append({
            "corp_code": corp, "fiscal_year": d["fiscal_year"],
            "fiscal_period": d["fiscal_period"], "statement_type": basis,
            "is_stub": False, "status": ra.status,
            "n_pass": ra.n_pass, "n_fail": ra.n_fail, "n_pending": ra.n_pending,
            "fail_fields": ra.fail_fields or None,
            "fail_detail": [
                {"field": f.field, "canonical": f.canonical, "db_won": f.db_amount_won,
                 "report_won": f.report_value_won, "reason": f.reason}
                for f in ra.fields if f.reason == "VALUE_DIFF"
            ] or None,
            "pending_detail": dict(pend) or None,
            "reader_version": READER_VERSION, "checked_at": datetime.utcnow(),
        })

    if batch and not args.no_commit:
        stmt = insert(FaceAudit).values(batch)
        upd = {c.name: stmt.excluded[c.name] for c in FaceAudit.__table__.columns
               if c.name not in ("corp_code", "fiscal_year", "fiscal_period",
                                 "statement_type", "is_stub")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["corp_code", "fiscal_year", "fiscal_period",
                            "statement_type", "is_stub"], set_=upd)
        session.execute(stmt)
        session.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--corps", help="corp_code 범위 LO:HI")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fy-min", type=int, default=2010)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    ensure_table()
    agg = {"status": Counter(), "fld_pass": 0, "fld_fail": 0, "fail_rows": []}
    with get_session() as session:
        corps = select_corps(session, args)
        print(f"대상 corp {len(corps)}사, fy>={args.fy_min}")
        for i, c in enumerate(corps, 1):
            audit_corp(session, c, args, agg)
            if i % 50 == 0:
                print(f"  ..{i}/{len(corps)}  status={dict(agg['status'])}")

    s = agg["status"]
    tot = sum(s.values())
    print(f"\n── 감사 {tot}행 ── pass {s['pass']} / fail {s['fail']} / pending {s['pending']}")
    if tot:
        promotable = s['pass'] + s['fail']
        print(f"   in-scope(=pass+fail) {promotable}행 중 일치율 = "
              f"{s['pass']/promotable*100:.1f}%" if promotable else "   in-scope 0")
        print(f"   필드: PASS {agg['fld_pass']} / FAIL {agg['fld_fail']}")
    if agg["fail_rows"]:
        print(f"\n── FAIL 행 {len(agg['fail_rows'])} (상위 20) ──")
        for corp, key, ff in agg["fail_rows"][:20]:
            print(f"   {corp} {key} → {ff}")


if __name__ == "__main__":
    main()
