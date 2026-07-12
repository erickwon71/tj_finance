"""
지표 카탈로그 enum — 단위 유형 / 카테고리 / 기간 grain.

표시·축 배치·포맷이 이 enum 으로 결정된다. 저장값은 항상 원시값(금액=원, 비율=소수).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UnitType(Enum):
    AMOUNT_EOK = "억원"    # 원시=원 → 표시 ÷1e8 (억원)
    PCT = "%"              # 원시=소수(0.15) → 표시 ×100 (%)
    MULTIPLE_X = "x"       # 배수/회전율
    DAYS = "일"            # 운전자본 일수
    WON_PER_SHARE = "원/주"  # 주당지표(금액÷주식수) — 원시=원/주 그대로 표시


class Category(Enum):
    FINANCIALS = "재무데이터"
    PROFIT = "수익성"
    GROWTH = "성장성"
    STABILITY = "안정성"
    EXTENDED = "확장 재무항목"


class Grain(Enum):
    ANNUAL = "annual"
    QUARTER = "quarter"


# 금액 단위만 좌축(억원), 나머지는 우축(비율/배수)으로 배치
AMOUNT_UNITS = {UnitType.AMOUNT_EOK}

EOK = 100_000_000
JO = 1_000_000_000_000


@dataclass(frozen=True)
class AmountScale:
    """AMOUNT_EOK 표시 스케일(Phase 5, D5) — 저장값(원)은 불변, 나눗셈은 표시 레이어 전용."""
    label: str
    factor: float
    decimals: int = 0


# 원/억원/조원 — 차트빌더 스케일 토글용. 기본값(하위호환) = 억원(기존 동작과 동일).
AMOUNT_SCALES: dict[str, AmountScale] = {
    "won": AmountScale("원", 1, 0),
    "eok": AmountScale("억원", EOK, 0),
    "jo": AmountScale("조원", JO, 2),
}
DEFAULT_AMOUNT_SCALE = AMOUNT_SCALES["eok"]


def display_value(value, unit: UnitType, amount_scale: AmountScale = DEFAULT_AMOUNT_SCALE):
    """원시값 → 표시값(숫자). None 안전. amount_scale 은 AMOUNT_EOK 단위에만 적용."""
    if value is None:
        return None
    if unit == UnitType.AMOUNT_EOK:
        return value / amount_scale.factor
    if unit == UnitType.PCT:
        return value * 100
    return value  # MULTIPLE_X, DAYS, WON_PER_SHARE = 그대로


def format_value(value, unit: UnitType, amount_scale: AmountScale = DEFAULT_AMOUNT_SCALE) -> str:
    """원시값 → 표시 문자열."""
    dv = display_value(value, unit, amount_scale)
    if dv is None:
        return "—"
    if unit == UnitType.AMOUNT_EOK:
        return f"{dv:,.{amount_scale.decimals}f}"
    if unit == UnitType.PCT:
        return f"{dv:.1f}%"
    if unit == UnitType.MULTIPLE_X:
        return f"{dv:.2f}x"
    if unit == UnitType.DAYS:
        return f"{dv:.0f}일"
    if unit == UnitType.WON_PER_SHARE:
        return f"{dv:,.0f}원"
    return f"{dv:,.2f}"
