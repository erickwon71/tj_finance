"""
app.registry.units 회귀 테스트 — 단위 변환·부호·포맷 (W8: 표시계층 무검증 해소).

원시값(금액=원, 비율=소수, 주당=원/주)을 표시값/문자열로 바꾸는 규칙을 고정한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.registry.units import UnitType, display_value, format_value  # noqa: E402
from tests._util import approx, run_tests  # noqa: E402

_EOK = 100_000_000


def test_display_amount_eok():
    assert approx(display_value(150 * _EOK, UnitType.AMOUNT_EOK), 150.0)
    assert approx(display_value(-3 * _EOK, UnitType.AMOUNT_EOK), -3.0)


def test_display_pct_and_passthrough():
    assert approx(display_value(0.153, UnitType.PCT), 15.3)
    assert approx(display_value(2.5, UnitType.MULTIPLE_X), 2.5)
    assert approx(display_value(36.5, UnitType.DAYS), 36.5)
    assert approx(display_value(5230.0, UnitType.WON_PER_SHARE), 5230.0)


def test_display_none():
    for u in UnitType:
        assert display_value(None, u) is None


def test_format_amount():
    assert format_value(150 * _EOK, UnitType.AMOUNT_EOK) == "150"
    assert format_value(1234 * _EOK, UnitType.AMOUNT_EOK) == "1,234"


def test_format_pct_sign():
    assert format_value(0.153, UnitType.PCT) == "15.3%"
    assert format_value(-0.05, UnitType.PCT) == "-5.0%"


def test_format_multiple_days_pershare():
    assert format_value(2.567, UnitType.MULTIPLE_X) == "2.57x"
    assert format_value(55.0, UnitType.DAYS) == "55일"
    assert format_value(5230.0, UnitType.WON_PER_SHARE) == "5,230원"


def test_format_none_dash():
    assert format_value(None, UnitType.AMOUNT_EOK) == "—"
    assert format_value(None, UnitType.PCT) == "—"


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
