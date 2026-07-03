"""데이터 신뢰 로더 — Gate B(보고서==DB) 감사 결과 요약. UI 비의존.

face_audit(독립 reader 로 보고서 면표 ↔ std_v2 대조) 를 corp 단위로 집계해 '이 기업 재무값이
공시 보고서와 일치하는가'를 배지로 보여준다. fail_a=확정 불일치(차단), fail(=fail_b)=휴리스틱 검토,
pending=검증 범위 밖.
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session


def load_trust(corp_code: str) -> dict:
    """face_audit 집계. {total, pass, fail, pending, fail_a}."""
    with get_session() as s:
        by = dict(s.execute(text(
            "SELECT status, count(*) FROM face_audit WHERE corp_code = :c GROUP BY status"),
            {"c": corp_code}).fetchall())
        fail_a = s.execute(text(
            "SELECT count(*) FROM face_audit WHERE corp_code = :c AND gate_status = 'fail_a'"),
            {"c": corp_code}).scalar() or 0
    return {
        "total": sum(by.values()),
        "pass": by.get("pass", 0), "fail": by.get("fail", 0),
        "pending": by.get("pending", 0), "fail_a": fail_a,
    }
