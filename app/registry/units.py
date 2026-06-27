"""
지표 카탈로그 enum — 단위 유형 / 카테고리 / 기간 grain.

표시·축 배치·포맷이 이 enum 으로 결정된다. 저장값은 항상 원시값(금액=원, 비율=소수).
"""
from __future__ import annotations

from enum import Enum


class UnitType(Enum):
    AMOUNT_EOK = "억원"    # 원시=원 → 표시 ÷1e8 (억원)
    PCT = "%"              # 원시=소수(0.15) → 표시 ×100 (%)
    MULTIPLE_X = "x"       # 배수/회전율
    DAYS = "일"            # 운전자본 일수


class Category(Enum):
    FINANCIALS = "재무데이터"
    PROFIT = "수익성"
    GROWTH = "성장성"
    STABILITY = "안정성"


class Grain(Enum):
    ANNUAL = "annual"
    QUARTER = "quarter"


# 금액 단위만 좌축(억원), 나머지는 우축(비율/배수)으로 배치
AMOUNT_UNITS = {UnitType.AMOUNT_EOK}

EOK = 100_000_000


def display_value(value, unit: UnitType):
    """원시값 → 표시값(숫자). None 안전."""
    if value is None:
        return None
    if unit == UnitType.AMOUNT_EOK:
        return value / EOK
    if unit == UnitType.PCT:
        return value * 100
    return value  # MULTIPLE_X, DAYS = 그대로


def format_value(value, unit: UnitType) -> str:
    """원시값 → 표시 문자열."""
    dv = display_value(value, unit)
    if dv is None:
        return "—"
    if unit == UnitType.AMOUNT_EOK:
        return f"{dv:,.0f}"
    if unit == UnitType.PCT:
        return f"{dv:.1f}%"
    if unit == UnitType.MULTIPLE_X:
        return f"{dv:.2f}x"
    if unit == UnitType.DAYS:
        return f"{dv:.0f}일"
    return f"{dv:,.2f}"
