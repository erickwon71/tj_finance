"""
face_audit.gate_status 보수적 백필 (task #5, 1회·멱등).

배경: gate_status(promote 게이트) 컬럼은 신규. 기존 face_audit 행은 track 미저장이라 fail 의
Track A/B 구분을 사후 도출할 수 없다. ⟹ 보수적 매핑으로 1회 채운다:
  pass→pass, pending→pending, fail→**fail_a**(=메인뷰 차단; 일부가 실제 Track B false-fail 이어도
  소수 over-block 은 안전). 이후 `gateb_audit.py --recheck` 재감사가 fail_a/fail_b 로 정밀화한다.

gate_status 가 이미 있는 행은 건너뜀(NULL 만 채움) → 멱등·재감사 결과 보존.

실행: PYTHONPATH=. .venv_tj_finance/bin/python scripts/gateb_backfill_gate_status.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

BACKFILL_SQL = """
UPDATE face_audit
SET gate_status = CASE status
    WHEN 'pass' THEN 'pass'
    WHEN 'pending' THEN 'pending'
    ELSE 'fail_a'
END
WHERE gate_status IS NULL
"""


def main() -> None:
    with get_session() as session:
        before = dict(session.execute(text(
            "SELECT COALESCE(gate_status,'(null)'), COUNT(*) FROM face_audit GROUP BY 1")).fetchall())
        logger.info(f"[gate_status] before: {before}")
        n = session.execute(text(BACKFILL_SQL)).rowcount
        session.commit()
        after = dict(session.execute(text(
            "SELECT COALESCE(gate_status,'(null)'), COUNT(*) FROM face_audit GROUP BY 1")).fetchall())
        logger.success(f"[gate_status] {n:,}행 백필 — after: {after}")


if __name__ == "__main__":
    main()
