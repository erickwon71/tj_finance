"""collector.market_calendar 회귀 테스트 — 데일리 휴장일 스킵 판정.

고정하는 사실:
  ① 주말·공휴일은 휴장(스킵), 평일 개장일은 실행
  ② **판정 불가는 개장일**(fail-open). 잘못 쉬면 그날 수집이 통째로 비고, 잘못 돌면
     API 를 몇 번 헛치고 끝이다 — 비대칭이 명확하다.
     달력 라이브러리가 없거나·고장나거나·수록 범위를 벗어나도 반드시 실행돼야 한다.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import market_calendar as mc  # noqa: E402
from tests._util import run_tests  # noqa: E402


# ── ① 개장/휴장 ─────────────────────────────────────────────────────

def test_weekend_is_not_trading_day():
    assert not mc.is_trading_day(date(2026, 8, 1)), "토요일"
    assert not mc.is_trading_day(date(2026, 8, 2)), "일요일"


def test_public_holiday_is_not_trading_day():
    """주말이 아닌 휴장일 — 하드코딩 목록이 아니라 XKRX 달력이 알아야 한다."""
    assert not mc.is_trading_day(date(2026, 12, 25)), "성탄절(금)"
    assert not mc.is_trading_day(date(2027, 1, 1)), "신정(금)"


def test_ordinary_weekday_is_trading_day():
    assert mc.is_trading_day(date(2026, 8, 3)), "평일 월요일"
    assert mc.is_trading_day(date(2026, 7, 31)), "평일 금요일"


def test_skip_reason_only_on_holidays():
    assert mc.skip_reason(date(2026, 8, 3)) is None, "개장일에 사유가 나왔다"
    r = mc.skip_reason(date(2026, 8, 1))
    assert r and "주말" in r and "2026-08-03" in r, r
    r = mc.skip_reason(date(2026, 12, 25))
    assert r and "공휴일" in r, r


# ── ② fail-open ─────────────────────────────────────────────────────

def _with_broken_calendar(fn):
    saved = mc._calendar

    def boom():
        raise RuntimeError("달력 라이브러리 고장")

    mc._calendar = boom
    try:
        return fn()
    finally:
        mc._calendar = saved


def test_calendar_failure_fails_open():
    """라이브러리가 죽어도 **실행**해야 한다 — 조용히 쉬면 그날 수집이 사라진다."""
    assert _with_broken_calendar(lambda: mc.is_trading_day(date(2026, 8, 1))) is True
    assert _with_broken_calendar(lambda: mc.skip_reason(date(2026, 8, 1))) is None


def test_out_of_range_date_fails_open():
    """달력 수록 범위(현재 ~2027)를 넘어선 날짜도 개장일 취급."""
    assert mc.is_trading_day(date(2099, 1, 3)) is True
    assert mc.skip_reason(date(2099, 1, 3)) is None


def test_next_trading_day_skips_weekend():
    assert mc.next_trading_day(date(2026, 7, 31)) == date(2026, 8, 3)


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
