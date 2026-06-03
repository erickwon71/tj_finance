"""
DART API 호출 속도 제한기
- 하루 40,000콜 한도 관리
- 콜 간 최소 1.0초 간격 강제 (config.MIN_REQUEST_INTERVAL)
- 자정 기준 일일 카운터 자동 리셋
- 한도 초과 시 DailyQuotaReached 예외를 던져 즉시 종료 (진행 상태는 DB에 저장됨)
"""
import time
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Optional

from loguru import logger

from collector.config import DAILY_CALL_LIMIT, MIN_REQUEST_INTERVAL


class DailyQuotaReached(Exception):
    """DART API 일일 호출 한도 도달 — 즉시 종료 신호 (자정까지 대기하지 않음)"""


class DartRateLimiter:
    """
    Thread-safe DART API rate limiter.

    사용 예:
        limiter = DartRateLimiter()
        limiter.wait()        # API 호출 전 반드시 호출
        response = requests.get(...)
    """

    def __init__(
        self,
        daily_limit: int = DAILY_CALL_LIMIT,
        min_interval: float = MIN_REQUEST_INTERVAL,  # config에서 1.0초
    ):
        self.daily_limit    = daily_limit
        self.min_interval   = min_interval
        self._lock          = Lock()
        self._calls_today   = 0
        self._day           = date.today()
        self._last_call_ts  = 0.0  # epoch seconds

    # ── 공개 메서드 ──────────────────────────────────────────────
    def wait(self) -> None:
        """
        API 호출 직전 반드시 호출.
        필요한 만큼 sleep한 뒤 반환하면 즉시 API 호출 가능.
        """
        with self._lock:
            self._maybe_reset_daily_counter()
            self._wait_for_daily_limit()
            self._wait_for_min_interval()
            self._calls_today += 1
            self._last_call_ts = time.monotonic()

    @property
    def calls_today(self) -> int:
        with self._lock:
            self._maybe_reset_daily_counter()
            return self._calls_today

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.calls_today)

    # ── 내부 메서드 ──────────────────────────────────────────────
    def _maybe_reset_daily_counter(self) -> None:
        today = date.today()
        if today != self._day:
            logger.info(
                f"[RateLimiter] 날짜 변경 → 일일 카운터 리셋 "
                f"(어제 {self._calls_today}콜 소비)"
            )
            self._calls_today = 0
            self._day = today

    def _wait_for_daily_limit(self) -> None:
        if self._calls_today < self.daily_limit:
            return

        # 자정까지 남은 시간 (참고용 로그)
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        wait_hours = ((midnight - now).total_seconds()) / 3600

        # 12시간 가까이 잠들지 않고 즉시 종료한다. 진행 상태는 DB에 저장되어 있으므로
        # 자정 이후(또는 다음 실행 시) 다시 실행하면 중단 지점부터 이어서 처리된다.
        logger.warning(
            f"[RateLimiter] 일일 한도 {self.daily_limit:,}콜 도달 — 즉시 종료합니다. "
            f"자정까지 약 {wait_hours:.1f}시간 남음. "
            f"자정 이후 다시 실행하면 중단 지점부터 재개됩니다."
        )
        raise DailyQuotaReached(
            f"일일 호출 한도 {self.daily_limit:,}콜 도달"
        )

    def _wait_for_min_interval(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)


# 프로세스 전역 싱글톤 인스턴스
_limiter: Optional[DartRateLimiter] = None


def get_limiter() -> DartRateLimiter:
    """모듈 전역 rate limiter 싱글톤 반환"""
    global _limiter
    if _limiter is None:
        _limiter = DartRateLimiter()
    return _limiter
