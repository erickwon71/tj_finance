"""
Gate B 생산 감사 러너 — std_v2/v3 행을 원본 보고서 face 표와 대조해 face_audit 대장 적재.

각 (corp,fy,fp,basis) 행을 audit_std_row 로 판정 → face_audit upsert.
status: pass(promote 가능) / fail(값불일치, 차단) / pending(범위밖).

--source v2(디폴트)/v3 로 감사 대상 std 체인을 고른다(2026-08-11,
docs/plans/std_v3_native_gate_b_plan_2026-08-11.md Phase 1). face_audit PK 에 source_version
이 있어 같은 (corp,fy,fp,basis) 키를 v2/v3 감사결과가 각자 별도 행으로 병행 보관 — 서로
덮어쓰지 않는다. v3 는 is_stub/is_discrete 개념도 comparative_fallback 개념도 없어(Phase 0
실측 확인) 그 필터/분기는 v2 전용으로 남긴다.

대량 = XML 파일 다수 open → **장시간**(사용자 실행 권장). 소표본은 --corps/--limit/--sample.

usage:
  python scripts/gateb_audit.py --corps 00000000:00200000   # corp_code 범위(v2)
  python scripts/gateb_audit.py --sample 50                 # 무작위 50사(v2)
  python scripts/gateb_audit.py --corp 00162416             # 단일(v2)
  python scripts/gateb_audit.py --source v3 --sample 50     # std_v3 감사
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
from collector.models import FaceAudit, FaceLineAudit, Base
from fin2.audit.face_audit import (
    read_report_face_tracked, audit_std_row, gate_status_for_row, STD_FIELD_CANONICAL,
)
from fin2.audit.line_audit import reconcile_report_lines, reconcile_report_lines_text

READER_VERSION = "trackAB-v2"
_DETAIL_CAP = 200   # JSONB 상세 라인 상한(대량 보고서 방어)

# 표준필드 → statement('BS'/'IS'/'CF', source-agnostic dict 키. §_row_rcepts 참고)
_FIELD_STMT = {"bs.": "BS", "is.": "IS", "cf.": "CF"}


def _field_track(field: str, rc: dict, track_of: dict) -> str | None:
    """실패필드 → canonical 접두 → statement → 그 rcept 를 읽은 track('A'/'B')."""
    canon = STD_FIELD_CANONICAL.get(field, "")
    stmt = _FIELD_STMT.get(canon[:3])
    return track_of.get(rc.get(stmt)) if stmt else None


def _row_rcepts(d: dict, source: str) -> dict:
    """std 행(dict) → {"BS":rcept,"IS":rcept,"CF":rcept}, source(v2/v3) 무관 공통 모양.

    v2 는 평면 컬럼(bs_rcept/is_rcept/cf_rcept), v3 는 source_rcepts JSONB
    ({"BS":rcept,...}) — Phase 0 실측(2026-08-11) 으로 NULL·3키 동시결측 0건 확인,
    개별 키 결측은 정상 시나리오(그 statement 가 그 filing 에 없음)이라 .get() 으로 충분.
    """
    if source == "v3":
        return dict(d.get("source_rcepts") or {})
    return {"BS": d.get("bs_rcept"), "IS": d.get("is_rcept"), "CF": d.get("cf_rcept")}


def ensure_table():
    # init_db() = create_all(전 테이블) + 대기 마이그레이션 적용(collector/db.py::_run_migrations).
    # face_audit 의 source_version 컬럼(2026_08_face_audit_source_version)처럼 스키마 변경이
    # create_all 만으론 안 걸리는 경우가 있어 이걸로 대체(기존 create_all 단독 호출보다 상위집합).
    from collector.db import init_db
    init_db()


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
    if args.source == "v3":
        q = "SELECT DISTINCT corp_code FROM std_financials_v3"
        where = " WHERE"
    else:
        q = "SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=1"
        where = " AND"
    params = {}
    if args.corps:
        lo, hi = args.corps.split(":")
        q += f"{where} corp_code >= :lo AND corp_code < :hi"
        params = {"lo": lo, "hi": hi}
    q += " ORDER BY corp_code"
    corps = [r.corp_code for r in session.execute(text(q), params)]
    if args.sample:
        random.seed(args.seed)
        corps = random.sample(corps, min(args.sample, len(corps)))
    return corps


def audit_corp(session, corp, args, agg):
    if args.source == "v3":
        # v3엔 version/is_stub/is_discrete 컬럼 자체가 없다(Phase 0 확인, fin2/layer3/build.py:41).
        # is_discrete 는 v2 뷰도 원래 걸러내던 파생행이라 필터 부재가 손실이 아니고,
        # is_stub 는 v2 기준 0.09%뿐이라 무시 가능 — 별도 필터 없이 std_v3 전체를 감사한다.
        rows = session.execute(text("""
            SELECT * FROM std_financials_v3
            WHERE corp_code=:c AND fiscal_year >= :fymin AND fiscal_year <= :fymax
            ORDER BY fiscal_year DESC
        """), {"c": corp, "fymin": args.fy_min, "fymax": args.fy_max}).fetchall()
    else:
        rows = session.execute(text("""
            SELECT * FROM std_financials_v2
            WHERE corp_code=:c AND version=1 AND NOT COALESCE(is_stub,false)
              AND NOT COALESCE(is_discrete,false)
              AND fiscal_year >= :fymin AND fiscal_year <= :fymax
            ORDER BY fiscal_year DESC
        """), {"c": corp, "fymin": args.fy_min, "fymax": args.fy_max}).fetchall()
    if not rows:
        return

    if not args.recheck:
        done = {(r.fiscal_year, r.fiscal_period, r.statement_type) for r in session.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type FROM face_audit
            WHERE corp_code=:c AND NOT COALESCE(is_stub,false) AND source_version=:sv
        """), {"c": corp, "sv": args.source})}
    else:
        done = set()

    # 이 corp 의 모든 source rcept 파일을 1회씩 읽어 캐시
    rcepts = set()
    for r in rows:
        for rc in _row_rcepts(dict(r._mapping), args.source).values():
            if rc:
                rcepts.add(rc)
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
        rc = _row_rcepts(d, args.source)
        if args.source == "v3":
            # v3(fin2/layer3/combine.py)엔 comparative-column-fallback 개념이 없다(grep 0건,
            # Phase 0 §2-4 확정) — 값이 있으면 항상 그 filing 자신의 col0. 항상 엄격 대조.
            is_comp = False
        else:
            rules = d.get("applied_rules") or []
            is_comp = "comparative_fallback" in rules
        # 비교행은 값이 후속보고서 전기/전전기 컬럼 → all_cols face 로 검증.
        ra = audit_std_row(
            d, basis=basis,
            bs_face=face_of(rc.get("BS"), all_cols=is_comp),
            is_face=face_of(rc.get("IS"), all_cols=is_comp),
            cf_face=face_of(rc.get("CF"), all_cols=is_comp),
            is_comparative=is_comp,
        )
        # promote gate_status: 실패필드 track('A'/'B')으로 fail_a(확정버그)/fail_b(휴리스틱) 분리
        fail_tracks = {f: _field_track(f, rc, track_of) for f in ra.fail_fields}
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
            "is_stub": False, "source_version": args.source,
            "status": ra.status, "gate_status": gate,
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
                                 "statement_type", "is_stub", "source_version")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["corp_code", "fiscal_year", "fiscal_period",
                            "statement_type", "is_stub", "source_version"], set_=upd)
        session.execute(stmt)
        session.commit()

    # ── Phase B: 본문 전 계정 라인 전수 대조(Track A+B) → face_line_audit ───────────────
    if getattr(args, "line_audit", True):
        audit_lines(session, corp, rcepts, face_of, track_of, args, agg)


def audit_lines(session, corp, rcepts, face_of, track_of, args, agg):
    """corp 의 전 source rcept 에 대해 보고서 face 라인을 fact_v2 와 대조 → face_line_audit.

    face 는 std-row 패스에서 이미 읽힌 face_cache 재사용(추가 XML 파싱 없음).
    Track A(XBRL acode 정확대조)·Track B(텍스트, C1: canonical 값-집합) 모두 pass/fail_a
    등급. PDF(C)·0라인은 pending(본 단계 비대상).

    ★ `fact_v2` 커버리지 참고(2026-08-09) — 상세는 `fin2/audit/line_audit.py` 모듈 docstring.
      요지: `fact_v2`가 아직 전체 rcept 의 일부에만 있어(≈2.4%, 2026-08-09 시점) 대다수
      rcept 는 `n_missing` 이 전량으로 나오지만, 등급(`line_gate_status`)은 값불일치만
      보므로 오탐 차단은 아니다. "구 체인 은퇴로 fact_v2 가 비어 있다"는 2026-07-31 시점
      서술은 더 이상 정확하지 않다(신규 XBRL 파서가 채우는 중) — 다만 완전성 지표로 쓰기엔
      아직 이르다.
    """
    if not rcepts:
        return
    line_agg = agg.setdefault("line", Counter())
    gate_agg = agg.setdefault("line_gate", Counter())

    # 재개: 이미 감사된 rcept skip(--recheck 면 전부 재검)
    if not args.recheck:
        done = {r[0] for r in session.execute(text(
            "SELECT rcept_no FROM face_line_audit WHERE corp_code=:c"), {"c": corp})}
    else:
        done = set()
    todo = [rc for rc in rcepts if rc not in done]
    if not todo:
        return

    # fact_v2 col0 비차원 행을 rcept 별로 1회 로드 (canonical_account = Track B 값-집합 대조용)
    fact_by_rcept: dict[str, list[dict]] = {}
    for r in session.execute(text("""
        SELECT rcept_no, acode, canonical_account, basis, is_cumulative, adecimal, amount_won
        FROM fact_v2
        WHERE rcept_no = ANY(:rs) AND col_index = 0 AND NOT COALESCE(is_dimensional, false)
    """), {"rs": todo}):
        fact_by_rcept.setdefault(r.rcept_no, []).append({
            "acode": r.acode, "canonical_account": r.canonical_account,
            "basis": r.basis, "is_cumulative": r.is_cumulative,
            "adecimal": r.adecimal, "amount_won": r.amount_won})

    batch = []
    for rc in todo:
        face = face_of(rc)                  # 캐시 재사용(col0 라인)
        track = track_of.get(rc)
        facts = fact_by_rcept.get(rc, [])
        if track == "B":
            # Track B(텍스트, C1): canonical 값-집합 대조. value_diff→fail_a(측정), missing=커버 갭.
            rla = reconcile_report_lines_text(rc, face, facts)
            gate = rla.line_gate_status if rla.n_lines > 0 else "pending"
            n_extra = 0                     # 텍스트는 역방향 잉여 무의미(reader=매핑라인만)
        else:
            # Track A: XBRL acode 정확대조. 그 외(C/None)는 n_lines 0 → pending.
            rla = reconcile_report_lines(rc, face, facts)
            is_a = track == "A" and rla.n_lines > 0
            gate = rla.line_gate_status if is_a else "pending"
            # pending 보고서는 신뢰할 face 가 없어 EXTRA 무의미 → Track A 일 때만 기록.
            n_extra = rla.n_extra if is_a else 0
        graded = gate != "pending"          # A/B 등급 부여된 보고서만 value_diff 집계
        line_agg["lines"] += rla.n_lines
        line_agg["match"] += rla.n_match
        line_agg["value_diff"] += rla.n_value_diff if graded else 0
        line_agg["missing"] += rla.n_missing
        gate_agg[gate] += 1
        batch.append({
            "rcept_no": rc, "corp_code": corp, "track": track,
            "n_lines": rla.n_lines, "n_match": rla.n_match,
            "n_value_diff": rla.n_value_diff, "n_missing": rla.n_missing,
            "n_extra": n_extra, "line_gate_status": gate,
            "value_diff_detail": [
                {"acode": l.acode, "basis": l.basis, "statement": l.statement,
                 "label": l.label, "report_won": l.report_won, "db_won": l.db_won}
                for l in rla.value_diffs[:_DETAIL_CAP]] or None,
            "missing_detail": [
                {"acode": l.acode, "basis": l.basis, "statement": l.statement, "label": l.label}
                for l in rla.missing[:_DETAIL_CAP]] or None,
            "reader_version": READER_VERSION, "checked_at": datetime.utcnow(),
        })

    if batch and not args.no_commit:
        stmt = insert(FaceLineAudit).values(batch)
        upd = {c.name: stmt.excluded[c.name] for c in FaceLineAudit.__table__.columns
               if c.name != "rcept_no"}
        stmt = stmt.on_conflict_do_update(index_elements=["rcept_no"], set_=upd)
        session.execute(stmt)
        session.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["v2", "v3"], default="v2",
                    help="감사할 std 체인. v3 는 docs/plans/std_v3_native_gate_b_plan_2026-08-11.md")
    ap.add_argument("--corp")
    ap.add_argument("--corp-file", dest="corp_file", help="corp_code 목록 파일(라인당 1개)")
    ap.add_argument("--corps", help="corp_code 범위 LO:HI")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fy-min", type=int, default=2010)
    ap.add_argument("--fy-max", type=int, default=2100)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-line-audit", dest="line_audit", action="store_false",
                    help="Phase B 라인 전수대조(face_line_audit) 비활성")
    ap.set_defaults(line_audit=True)
    args = ap.parse_args()

    ensure_table()
    agg = {"status": Counter(), "gate": Counter(), "fld_pass": 0, "fld_fail": 0,
           "fail_rows": [], "errors": 0}
    with get_session() as session:
        corps = select_corps(session, args)
        print(f"대상 corp {len(corps)}사, source={args.source}, fy>={args.fy_min}")
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

    if args.line_audit and agg.get("line"):
        ln = agg["line"]; lg = agg.get("line_gate", Counter())
        print(f"\n── Phase B 라인 전수대조(Track A+B) ── 라인 {ln['lines']}: "
              f"match {ln['match']} / value_diff(차단후보) {ln['value_diff']} / "
              f"missing(완전성지표) {ln['missing']}")
        print(f"   보고서 gate: pass {lg['pass']} / fail_a {lg['fail_a']} / pending {lg['pending']}")


if __name__ == "__main__":
    main()
