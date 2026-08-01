"""거래소 개장일 판정 — 데일리를 휴장일에 돌리지 않기 위한 최소 계층.

왜 필요한가
───────────
정기보고서 접수도, 시세도, 상장/폐지도 전부 **영업일에만** 생긴다. 휴장일 실행은 아무것도
얻지 못하면서 KRX·DART API 만 헛치고, 그때마다 "빈 목록(HTTP 200)" 경로를 밟는다.

왜 launchd 가 아니라 여기인가
─────────────────────────────
plist `StartCalendarInterval` 의 `Weekday` 로는 **주말밖에** 표현할 수 없다. 공휴일·임시휴장일은
어차피 코드에서 봐야 하므로 판정을 한곳에 둔다.

소스: `exchange_calendars` 의 XKRX 달력(대체공휴일·임시휴장일 포함, 상용 라이브러리가 유지보수).
하드코딩한 공휴일 목록은 두지 않는다 — 반드시 낡고, 낡은 것을 아무도 모른다.

★ 판정 불가는 **개장일로 본다(fail-open)**.
  잘못 쉬면 그날 수집이 통째로 빈다(복구는 다음 영업일 `--days auto` 에 의존).
  잘못 돌면 API 몇 번 헛치고 끝이다. 비대칭이 명확하므로 의심스러우면 돌린다.
  달력 라이브러리의 수록 범위(현재 ~2027-07)를 벗어나는 날도 같은 이유로 개장일 취급이다.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from loguru import logger

CALENDAR = "XKRX"          # 한국거래소
_WEEKDAY_KR = "월화수목금토일"


def _calendar():
    import exchange_calendars as xc
    return xc.get_calendar(CALENDAR)


def is_trading_day(day: Optional[date] = None) -> bool:
    """`day`(기본 오늘)가 KRX 개장일인가. 판정 불가면 True(fail-open)."""
    day = day or date.today()
    try:
        cal = _calendar()
        # 수록 범위를 벗어나면 라이브러리가 예외를 던진다 → fail-open 으로 흘린다.
        if day < cal.first_session.date() or day > cal.last_session.date():
            logger.warning(f"[calendar] {day} 가 {CALENDAR} 수록 범위 밖 "
                           f"(~{cal.last_session.date()}) — 개장일로 간주하고 진행. "
                           f"exchange_calendars 업데이트 필요.")
            return True
        return bool(cal.is_session(day.isoformat()))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[calendar] 개장일 판정 실패({type(exc).__name__}: {exc}) — "
                       f"개장일로 간주하고 진행")
        return True


def next_trading_day(day: Optional[date] = None) -> Optional[date]:
    """`day` **다음**(초과) 개장일. 로그·안내용이라 실패하면 None.

    `next_session()` 은 인자가 개장일이 아니면 NotSessionError 를 던진다(휴장일에 부르는 게
    이 함수의 본래 용도인데). 그래서 휴장일은 `date_to_session(direction='next')` 로 간다.
    """
    day = day or date.today()
    try:
        cal = _calendar()
        if cal.is_session(day.isoformat()):
            return cal.next_session(day.isoformat()).date()
        return cal.date_to_session(day.isoformat(), direction="next").date()
    except Exception:  # noqa: BLE001
        return None


def skip_reason(day: Optional[date] = None) -> Optional[str]:
    """휴장일이면 사람이 읽을 사유 문자열, 개장일이면 None.

    호출부가 `if reason: 로그 남기고 종료` 한 줄로 끝나도록 판정+문구를 여기서 만든다.
    """
    day = day or date.today()
    if is_trading_day(day):
        return None
    kind = "주말" if day.weekday() >= 5 else "공휴일·휴장일"
    nxt = next_trading_day(day)
    return (f"{day} ({_WEEKDAY_KR[day.weekday()]}) {kind} — KRX 휴장"
            + (f". 다음 개장일 {nxt}" if nxt else ""))
