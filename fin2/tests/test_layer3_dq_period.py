"""
Layer 3 (std_v3) data_quality/period_end 백필 단위 테스트 (Phase 1, 2026-08-09).

DB-비의존 순수 함수만 다룬다(프로젝트 관례: fin2/tests/test_*.py 는 전부 DB-free —
_dq_cross_year_v3/_period_end 는 세션이 필요한 조회 함수라 여기서 pytest 로 못 돈다.
v2 의 동형 함수(_dq_cross_year/_period_end)도 애초에 pytest 커버가 없었다. 그쪽은
실제 DB 대상 스모크 검증(삼성전자/경농/농심, 2026-08-09 세션)으로 확인했다 —
docs/plans/std_v3_dq_shares_period_backfill_todo_2026-08-09.md Phase 1 참고.

항등식 위반(validate_equations)은 fin2/standardize/rules.py 의 순수 함수를 v3 가
**그대로 재사용**하므로(재구현 아님) test_rules.py::test_validate_equations 가 이미
커버한다 — 여기서 중복하지 않는다.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.standardize.build import _future_guard  # noqa: E402


def test_future_guard_past_period_end_unchanged():
    past = date.today() - timedelta(days=1)
    assert _future_guard(1, past) == 1
    assert _future_guard(2, past) == 2


def test_future_guard_today_unchanged():
    # period_end == today 는 "미래"가 아니다(끝난 기간) → 원래 dq 유지.
    assert _future_guard(1, date.today()) == 1


def test_future_guard_future_forces_dq3():
    future = date.today() + timedelta(days=1)
    assert _future_guard(1, future) == 3
    assert _future_guard(2, future) == 3
    # 이미 3이면 그대로 3(하향 없음)
    assert _future_guard(3, future) == 3


def test_future_guard_none_period_end_unchanged():
    # period_end 미상(None) → 미래 여부를 판단 못하므로 dq 그대로(추측 금지).
    assert _future_guard(1, None) == 1
    assert _future_guard(2, None) == 2
