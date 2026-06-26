"""
기업별 순차 다운로드 + 보고서↔DB 전기간 검증 오케스트레이터
================================================================
활성 보통주를 corp_code 오름차순으로 하나씩 돌며, 각 기업의 전기간(상장 이후
분기/반기/사업보고서 전부)에 대해 아래 6단계를 1패스로 실행하고 기업 단위 커밋한다.

  1) sync-filings : DART 공시목록 최신화(+download_tasks 인큐)
  2) download     : 전기간 보고서 다운로드(멱등·재개)
  3) Gate A       : 파일 무결성 + 재무제표 존재 → download_tasks.gate_a_status
  4) fin2 chain   : E(extract)→R(reconcile)→S(standardize)→분기→달력 (run.process_corp)
  5) Gate B       : 보고서 face vs DB(std_v2 40필드, 연결+별도 전 fy) → face_audit
  6) rollup       : face_audit 집계 → corp_verify_status (전기간 pass/fail/pending)

설계 원칙(PRD 00): DB 적재 금액은 원본 보고서와 100% 일치해야 한다.
실패(보고서≠DB)해도 루프는 중단하지 않고 corp_verify_status.fail_periods 에 기록 후
다음 기업으로 계속(사용자 확정). 재개: stage='audited' 기업은 skip(--recheck 로 강제 재검).

⚠ 다운로드·Gate B 는 XML 다수 open → **장시간**. --corps/--shard 로 분할 권장.

usage:
  python scripts/verify_corp_sequential.py --corps 0:1        # 파일럿 1사
  python scripts/verify_corp_sequential.py --corps 0:10       # 소표본 10사
  python scripts/verify_corp_sequential.py --shard 0/8        # 8분할 중 0번 샤드
  옵션: --fy-min 2010 --recheck --skip-download --limit N
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.db import get_session, engine
from collector.models import Base, CorpVerifyStatus, FaceAudit, FaceLineAudit
from scripts.validate_downloads import integrity_reason
from scripts import gateb_audit


def ensure_tables():
    Base.metadata.create_all(
        engine, tables=[CorpVerifyStatus.__table__, FaceAudit.__table__,
                        FaceLineAudit.__table__], checkfirst=True)
    # 기존 corp_verify_status 테이블에 Phase B 롤업 컬럼 보강(create_all 은 컬럼 추가 안 함). 멱등.
    with engine.begin() as conn:
        for col in ("line_total", "line_value_diff", "line_missing"):
            conn.execute(text(
                f"ALTER TABLE corp_verify_status ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 0"))


def select_corps(session, args):
    """활성 보통주 corp_code 오름차순. --corps 인덱스 슬라이스 / --shard a/n 분할."""
    corps = [r[0] for r in session.execute(text(
        "SELECT corp_code FROM corporations WHERE is_active = TRUE ORDER BY corp_code"
    )).fetchall()]
    if args.corps:
        lo, _, hi = args.corps.partition(":")
        corps = corps[(int(lo) if lo else None):(int(hi) if hi else None)] if ":" in args.corps \
            else corps[int(args.corps):int(args.corps) + 1]
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        corps = [c for i, c in enumerate(corps) if i % n == a]
    if args.limit:
        corps = corps[:args.limit]
    return corps


def gate_a_corp(session, corp):
    """기업 단위 Gate A: completed download_tasks 의 파일 무결성 + fact_v2 존재 판정."""
    rows = session.execute(text("""
        SELECT dt.rcept_no AS rcept_no, dt.file_path AS file_path, dt.file_type AS file_type
        FROM download_tasks dt JOIN filings f ON f.rcept_no = dt.rcept_no
        WHERE f.corp_code = :c AND dt.status = 'completed'
    """), {"c": corp}).fetchall()
    if not rows:
        return
    fact_rcepts = {r[0] for r in session.execute(
        text("SELECT DISTINCT rcept_no FROM fact_v2 WHERE corp_code=:c"), {"c": corp}).fetchall()}
    for r in rows:
        reason = integrity_reason(r.file_path, r.file_type)
        if reason is not None:
            status = "FAIL"
        elif r.rcept_no not in fact_rcepts:
            status, reason = "REVIEW", "EXTRACT_EMPTY"
        else:
            status, reason = "PASS", None
        session.execute(text("""
            UPDATE download_tasks SET gate_a_status=:s, gate_a_reason=:r, gate_a_checked_at=:t
            WHERE rcept_no=:rc
        """), {"s": status, "r": reason, "t": datetime.utcnow(), "rc": r.rcept_no})


def rollup_corp(session, corp, corp_name, stage, error=None):
    """face_audit/std_v2/download_tasks 집계 → corp_verify_status upsert(전기간 요약·재개 마커)."""
    nf = session.execute(text(
        "SELECT count(*) FROM filings WHERE corp_code=:c"), {"c": corp}).scalar() or 0
    nd = session.execute(text("""
        SELECT count(*) FROM download_tasks dt JOIN filings f ON f.rcept_no=dt.rcept_no
        WHERE f.corp_code=:c AND dt.status='completed'
    """), {"c": corp}).scalar() or 0
    ga = dict(session.execute(text("""
        SELECT dt.gate_a_status AS s, count(*) AS n
        FROM download_tasks dt JOIN filings f ON f.rcept_no=dt.rcept_no
        WHERE f.corp_code=:c AND dt.gate_a_status IS NOT NULL GROUP BY dt.gate_a_status
    """), {"c": corp}).fetchall())
    n_std = session.execute(text(
        "SELECT count(*) FROM std_financials_v2 WHERE corp_code=:c AND version=1"),
        {"c": corp}).scalar() or 0
    gb = dict(session.execute(text(
        "SELECT status AS s, count(*) AS n FROM face_audit WHERE corp_code=:c GROUP BY status"),
        {"c": corp}).fetchall())
    gb_fail_a = session.execute(text(
        "SELECT count(*) FROM face_audit WHERE corp_code=:c AND gate_status='fail_a'"),
        {"c": corp}).scalar() or 0
    fail_periods = [[r.fiscal_year, r.fiscal_period, r.statement_type, r.gate_status]
                    for r in session.execute(text("""
        SELECT fiscal_year, fiscal_period, statement_type, gate_status FROM face_audit
        WHERE corp_code=:c AND status='fail' ORDER BY fiscal_year DESC, fiscal_period LIMIT 200
    """), {"c": corp}).fetchall()]

    # Phase B 라인 전수대조 롤업(face_line_audit, 전 source rcept)
    la = session.execute(text("""
        SELECT COALESCE(sum(n_lines),0) tot, COALESCE(sum(n_value_diff),0) vd,
               COALESCE(sum(n_missing),0) miss
        FROM face_line_audit WHERE corp_code=:c
    """), {"c": corp}).one()

    vals = {
        "corp_code": corp, "corp_name": corp_name, "stage": stage,
        "n_filings": nf, "n_downloaded": nd,
        "gate_a_pass": ga.get("PASS", 0), "gate_a_fail": ga.get("FAIL", 0),
        "n_std_rows": n_std,
        "gb_pass": gb.get("pass", 0), "gb_fail": gb.get("fail", 0),
        "gb_pending": gb.get("pending", 0), "gb_fail_a": gb_fail_a,
        "fail_periods": fail_periods or None, "error": error,
        "line_total": la.tot, "line_value_diff": la.vd, "line_missing": la.miss,
        "verified_at": datetime.utcnow(),
    }
    stmt = insert(CorpVerifyStatus).values(vals)
    upd = {k: stmt.excluded[k] for k in vals if k != "corp_code"}
    session.execute(stmt.on_conflict_do_update(index_elements=["corp_code"], set_=upd))
    return vals


def verify_corp(corp, corp_name, args):
    """한 기업 전기간 6단계 1패스. 예외는 잡아 corp_verify_status.error 에 기록."""
    from collector.filing_collector import sync_filings
    from collector.downloader import run_downloads
    from run import process_corp

    # 1) sync-filings  2) download  (각자 내부 세션 관리)
    if not args.skip_download:
        sync_filings(corp_codes=[corp])
        run_downloads(only_corp_codes=[corp])

    # 3) Gate A  +  4) fin2 chain (한 세션·기업 단위 커밋)
    with get_session() as s:
        gate_a_corp(s, corp)
        process_corp(s, corp)
        s.commit()

    # 5) Gate B (audit_corp 가 내부 커밋)
    gb_args = SimpleNamespace(
        corp=corp, corp_file=None, corps=None, sample=None, seed=42,
        fy_min=args.fy_min, fy_max=2100, recheck=args.recheck, no_commit=False,
        line_audit=True)
    gb_agg = {"status": Counter(), "gate": Counter(),
              "fld_pass": 0, "fld_fail": 0, "fail_rows": [], "errors": 0}
    with get_session() as s:
        gateb_audit.audit_corp(s, corp, gb_args, gb_agg)

    # 6) rollup
    with get_session() as s:
        vals = rollup_corp(s, corp, corp_name, stage="audited")
        s.commit()
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="corp_code 인덱스 슬라이스 LO:HI (활성 정렬 기준)")
    ap.add_argument("--shard", help="a/n 분할(i %% n == a)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--fy-min", dest="fy_min", type=int, default=2010)
    ap.add_argument("--recheck", action="store_true", help="audited 기업도 재검(Gate B recheck 포함)")
    ap.add_argument("--skip-download", dest="skip_download", action="store_true",
                    help="sync-filings/download 건너뛰고 적재·검증만(이미 받은 파일 재검증)")
    args = ap.parse_args()

    ensure_tables()
    with get_session() as s:
        corps = select_corps(s, args)
        names = dict(s.execute(text(
            "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:cs)"),
            {"cs": corps}).fetchall())
        done = set() if args.recheck else {r[0] for r in s.execute(text(
            "SELECT corp_code FROM corp_verify_status WHERE stage='audited'")).fetchall()}

    todo = [c for c in corps if c not in done]
    print(f"대상 {len(corps)}사 중 미검증 {len(todo)}사 처리 (skip {len(corps) - len(todo)})")

    tot = {"pass": 0, "fail": 0, "err": 0}
    for i, corp in enumerate(todo, 1):
        name = names.get(corp, "?")
        try:
            vals = verify_corp(corp, name, args)
            ok = vals["gb_fail_a"] == 0
            tot["pass" if ok else "fail"] += 1
            verdict = "PASS" if ok else f"FAIL(fail_a={vals['gb_fail_a']})"
            print(f"[{i}/{len(todo)}] {corp} {name} — std {vals['n_std_rows']} / "
                  f"GateB pass {vals['gb_pass']} fail {vals['gb_fail']} pend {vals['gb_pending']} "
                  f"→ {verdict}")
        except Exception as e:
            tot["err"] += 1
            msg = f"{type(e).__name__}: {e}"[:300]
            print(f"[{i}/{len(todo)}] {corp} {name} — [ERR] {msg}")
            try:
                with get_session() as s:
                    rollup_corp(s, corp, name, stage="error", error=msg)
                    s.commit()
            except Exception:
                pass

    print(f"\n── 완료: PASS {tot['pass']} / FAIL {tot['fail']} / ERR {tot['err']} ──")
    with get_session() as s:
        lb = s.execute(text("""
            SELECT COALESCE(sum(line_total),0) tot, COALESCE(sum(line_value_diff),0) vd,
                   COALESCE(sum(line_missing),0) miss FROM corp_verify_status
            WHERE corp_code = ANY(:cs)
        """), {"cs": todo}).one()
    print(f"   Phase B 라인: {lb.tot} 대조 / value_diff(차단후보) {lb.vd} / "
          f"missing(완전성지표) {lb.miss}")


if __name__ == "__main__":
    main()
