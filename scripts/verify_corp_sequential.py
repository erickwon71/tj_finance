"""
기업별 검증 롤업 — face_audit/face_line_audit/download_tasks 집계 → corp_verify_status upsert
================================================================
★2026-10-03 슬림화: 예전에는 기업별 순차 다운로드→Gate A→fin2 chain(process_corp)→Gate B(std_v2)→롤업
오케스트레이터였다. fact_v2·std_financials_v2 가 DROP(2026-09-01)돼 그 드라이버는 죽었고,
데일리 DQ 게이트(`scripts/collect_new.py::run_dq_gate`)가 쓰는 `ensure_tables`·`rollup_corp` 만 남겼다.
옛 전체 드라이버는 scripts/archive/dropped_v2/verify_corp_sequential_legacy.py 에 보존.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.db import engine
from collector.models import Base, CorpVerifyStatus, FaceAudit, FaceLineAudit


def ensure_tables():
    Base.metadata.create_all(
        engine, tables=[CorpVerifyStatus.__table__, FaceAudit.__table__,
                        FaceLineAudit.__table__], checkfirst=True)
    # 기존 corp_verify_status 테이블에 Phase B 롤업 컬럼 보강(create_all 은 컬럼 추가 안 함). 멱등.
    with engine.begin() as conn:
        for col in ("line_total", "line_value_diff", "line_missing"):
            conn.execute(text(
                f"ALTER TABLE corp_verify_status ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 0"))


def rollup_corp(session, corp, corp_name, stage, error=None):
    """face_audit/std_v3/download_tasks 집계 → corp_verify_status upsert(전기간 요약·재개 마커).

    face_audit 읽기는 source_version='v3' 로 한정한다 — 이 롤업이 요약하는 것은 데일리 DQ 게이트
    (`run_dq_gate`, `audit_corp(..., source="v3")`)가 방금 남긴 v3 감사결과다. 한정하지 않으면
    과거 v2 감사행(273,506건)까지 같은 (corp,fy,fp,basis) 키에서 합산돼 이중집계된다
    (2026-08-18, docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md §1-C)."""
    source = "v3"
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
        "SELECT count(*) FROM std_financials_v3 WHERE corp_code=:c"),
        {"c": corp}).scalar() or 0
    gb = dict(session.execute(text(
        "SELECT status AS s, count(*) AS n FROM face_audit "
        "WHERE corp_code=:c AND source_version=:sv GROUP BY status"),
        {"c": corp, "sv": source}).fetchall())
    gb_fail_a = session.execute(text(
        "SELECT count(*) FROM face_audit "
        "WHERE corp_code=:c AND source_version=:sv AND gate_status='fail_a'"),
        {"c": corp, "sv": source}).scalar() or 0
    fail_periods = [[r.fiscal_year, r.fiscal_period, r.statement_type, r.gate_status]
                    for r in session.execute(text("""
        SELECT fiscal_year, fiscal_period, statement_type, gate_status FROM face_audit
        WHERE corp_code=:c AND source_version=:sv AND status='fail'
        ORDER BY fiscal_year DESC, fiscal_period LIMIT 200
    """), {"c": corp, "sv": source}).fetchall()]

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
