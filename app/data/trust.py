"""데이터 신뢰 로더 — Gate B(보고서==DB) 감사 결과 요약. UI 비의존.

face_audit(독립 reader 로 보고서 면표 ↔ std_v3 대조) 를 corp 단위로 집계해 '이 기업 재무값이
공시 보고서와 일치하는가'를 배지로 보여준다. fail_a=확정 불일치(차단), fail(=fail_b)=휴리스틱 검토,
pending=검증 범위 밖.

face_audit 은 v2/v3 감사결과를 같은 키에 병행 보관한다(source_version 컬럼, 2026-08-11
`2026_08_face_audit_source_version`). standard_financials 뷰는 v3 데이터 행에 v3 감사만
붙이므로(2026-08-18 `2026_08_standard_financials_view_source_version`), 이 배지도 v3 로
한정한다 — 안 그러면 v2 감사행까지 합산돼 모집단이 2배가 되고 fail_a 카운트에 v2 결과가
섞인다(docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md §1-C/§2).
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session


def load_trust(corp_code: str) -> dict:
    """face_audit 집계(source_version='v3' 한정). {total, pass, fail, pending, fail_a}."""
    with get_session() as s:
        by = dict(s.execute(text(
            "SELECT status, count(*) FROM face_audit "
            "WHERE corp_code = :c AND source_version = 'v3' GROUP BY status"),
            {"c": corp_code}).fetchall())
        fail_a = s.execute(text(
            "SELECT count(*) FROM face_audit "
            "WHERE corp_code = :c AND source_version = 'v3' AND gate_status = 'fail_a'"),
            {"c": corp_code}).scalar() or 0
    return {
        "total": sum(by.values()),
        "pass": by.get("pass", 0), "fail": by.get("fail", 0),
        "pending": by.get("pending", 0), "fail_a": fail_a,
    }
