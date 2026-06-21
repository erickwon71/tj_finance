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
from __future__ import annotations

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
from fin2.audit.face_audit import (
    read_report_face_tracked, audit_std_row, gate_status_for_row, STD_FIELD_CANONICAL,
)

READER_VERSION = "trackAB-v2"

# 표준필드 → statement 의 source rcept 컬럼(track 조회용)
_FIELD_RCEPT_COL = {"bs.": "bs_rcept", "is.": "is_rcept", "cf.": "cf_rcept"}


def _field_track(field: str, db_row: dict, track_of: dict) -> str | None:
    """실패필드 → canonical 접두 → statement source rcept → 그 rcept 를 읽은 track('A'/'B')."""
    canon = STD_FIELD_CANONICAL.get(field, "")
    col = _FIELD_RCEPT_COL.get(canon[:3])
    return track_of.get(db_row.get(col)) if col else None


def ensure_table():
    Base.metadata.create_all(engine, tables=[FaceAudit.__table__], checkfirst=True)


def file_path_map(session, rcepts):
    """rcept_no 집합 → file_path. xml 우선, 없으면 pdf(Track C, PDF-only 보고서 검증)."""
    if not rcepts:
        return {}
    rows = session.execute(text("""
        SELECT rcept_no, file_path, file_type FROM download_tasks
        WHERE rcept_no = ANY(:rs) AND file_type IN ('xml','pdf') AND status='completed'
          AND file_path IS NOT NULL
    """), {"rs": list(rcepts)}).fetchall()
    fmap: dict[str, str] = {}
    for r in rows:
        # xml 이 이미 있으면 유지(우선). 없을 때만 pdf 채택.
        if r.file_type == "xml" or r.rcept_no not in fmap:
            fmap[r.rcept_no] = r.file_path
    return fmap


def select_corps(session, args):
    if args.corp:
        return [args.corp]
    if args.corp_file:
        corps = [ln.strip() for ln in Path(args.corp_file).read_text().splitlines() if ln.strip()]
        return sorted(set(corps))
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
          AND fiscal_year >= :fymin AND fiscal_year <= :fymax
        ORDER BY fiscal_year DESC
    """), {"c": corp, "fymin": args.fy_min, "fymax": args.fy_max}).fetchall()
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
    face_cache_all: dict[str, list] = {}   # all_cols(비교행 검증용)
    track_of: dict[str, str | None] = {}   # rcept → 'A'/'B'/None (gate_status 분류용)

    def face_of(rc, all_cols=False):
        if not rc:
            return []
        cache = face_cache_all if all_cols else face_cache
        if rc not in cache:
            fp = fpmap.get(rc)
            try:
                lines, track = read_report_face_tracked(fp, all_cols=all_cols) if fp else ([], None)
            except (FileNotFoundError, OSError):
                # 소실/손상 파일(Gate A MISSING_FILE 등) → face 없음 → 해당 행 pending(크래시 아님)
                lines, track = [], None
            cache[rc] = lines
            if not all_cols:
                track_of[rc] = track
        return cache[rc]

    batch = []
    for r in rows:
        d = dict(r._mapping)
        key = (d["fiscal_year"], d["fiscal_period"], d["statement_type"])
        if key in done:
            continue
        basis = d["statement_type"]
        rules = d.get("applied_rules") or []
        is_comp = "comparative_fallback" in rules
        # 비교행은 값이 후속보고서 전기/전전기 컬럼 → all_cols face 로 검증.
        ra = audit_std_row(
            d, basis=basis,
            bs_face=face_of(d.get("bs_rcept"), all_cols=is_comp),
            is_face=face_of(d.get("is_rcept"), all_cols=is_comp),
            cf_face=face_of(d.get("cf_rcept"), all_cols=is_comp),
            is_comparative=is_comp,
        )
        # promote gate_status: 실패필드 track('A'/'B')으로 fail_a(확정버그)/fail_b(휴리스틱) 분리
        fail_tracks = {f: _field_track(f, d, track_of) for f in ra.fail_fields}
        gate = gate_status_for_row(ra, fail_tracks)
        agg["status"][ra.status] += 1
        agg["gate"][gate] += 1
        agg["fld_pass"] += ra.n_pass; agg["fld_fail"] += ra.n_fail
        if ra.status == "fail":
            agg["fail_rows"].append((corp, key, gate, ra.fail_fields))
        pend = Counter(f.reason for f in ra.fields if f.reason and f.reason != "VALUE_DIFF")
        batch.append({
            "corp_code": corp, "fiscal_year": d["fiscal_year"],
            "fiscal_period": d["fiscal_period"], "statement_type": basis,
            "is_stub": False, "status": ra.status, "gate_status": gate,
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
    ap.add_argument("--corp-file", dest="corp_file", help="corp_code 목록 파일(라인당 1개)")
    ap.add_argument("--corps", help="corp_code 범위 LO:HI")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fy-min", type=int, default=2010)
    ap.add_argument("--fy-max", type=int, default=2100)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    ensure_table()
    agg = {"status": Counter(), "gate": Counter(), "fld_pass": 0, "fld_fail": 0,
           "fail_rows": [], "errors": 0}
    with get_session() as session:
        corps = select_corps(session, args)
        print(f"대상 corp {len(corps)}사, fy>={args.fy_min}")
        for i, c in enumerate(corps, 1):
            try:
                audit_corp(session, c, args, agg)
            except Exception as e:
                # 기업 단위 예외 격리(전수 장시간 실행이 한 기업 오류로 중단되지 않게)
                session.rollback()
                agg["errors"] += 1
                print(f"  [err] corp={c}: {type(e).__name__}: {e}")
            if i % 50 == 0:
                print(f"  ..{i}/{len(corps)}  status={dict(agg['status'])} err={agg['errors']}")

    s = agg["status"]
    g = agg["gate"]
    tot = sum(s.values())
    print(f"\n── 감사 {tot}행 ── pass {s['pass']} / fail {s['fail']} / pending {s['pending']}"
          f" (기업오류 {agg['errors']})")
    print(f"   gate_status: pass {g['pass']} / fail_a(차단) {g['fail_a']} / "
          f"fail_b(REVIEW) {g['fail_b']} / pending {g['pending']}")
    if tot:
        promotable = s['pass'] + s['fail']
        print(f"   in-scope(=pass+fail) {promotable}행 중 일치율 = "
              f"{s['pass']/promotable*100:.1f}%" if promotable else "   in-scope 0")
        print(f"   필드: PASS {agg['fld_pass']} / FAIL {agg['fld_fail']}")
    if agg["fail_rows"]:
        print(f"\n── FAIL 행 {len(agg['fail_rows'])} (상위 20) ──")
        for corp, key, gate, ff in agg["fail_rows"][:20]:
            print(f"   [{gate}] {corp} {key} → {ff}")


if __name__ == "__main__":
    main()
