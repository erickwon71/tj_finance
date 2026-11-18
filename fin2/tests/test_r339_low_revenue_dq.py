"""R339: a FY revenue far below the corp median with normal total assets is DQ2, not DQ3.

DB-free: `_dq_cross_year_v3` only needs `session.execute(...).scalar()` for the two medians,
so a fake session returns them by column name.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.layer3.build as build  # noqa: E402
from fin2.layer3.build import _dq_cross_year_v3, _r339_low_revenue_is_real  # noqa: E402


class _Result:
    def __init__(self, v):
        self._v = v

    def scalar(self):
        return self._v


class _FakeSession:
    def __init__(self, medians: dict[str, float | None]):
        self.medians = medians

    def execute(self, stmt, params=None):
        sql = str(stmt)
        for col, med in self.medians.items():
            if f"ORDER BY {col})" in sql:
                return _Result(med)
        raise AssertionError(sql)


B = 1_000_000_000


def _dq(rev, ta, med_rev, med_ta):
    s = _FakeSession({"revenue": med_rev, "total_assets": med_ta})
    return _dq_cross_year_v3(s, "00000000", "separate", {"revenue": rev, "total_assets": ta})


def test_spin_off_holding_company_is_warning():
    # 경동인베스트 2017FY separate: revenue 0.61B vs median 584B, assets ratio 1.0
    assert _dq(612_436_467, 318 * B, 584 * B, 318 * B) == 2


def test_first_short_fiscal_year_is_warning():
    # 폰드그룹 2023FY separate (4-day period): revenue 0.85B vs median 180B, assets ratio 0.85
    assert _dq(847_667_601, 327 * B, 180 * B, 385 * B) == 2


def test_low_revenue_with_abnormal_assets_stays_dq3():
    assert _dq(1 * B, 1 * B, 584 * B, 318 * B) == 3


def test_high_revenue_outlier_stays_dq3():
    # upward x1000 may be a unit error
    assert _dq(584_000 * B, 318 * B, 584 * B, 318 * B) == 3


def test_no_assets_median_stays_dq3():
    assert _dq(612_436_467, 318 * B, 584 * B, None) == 3


def test_assets_outlier_still_dq3():
    assert _dq(500 * B, 318_000 * B, 584 * B, 318 * B) == 3


def test_normal_row_unchanged():
    assert _dq(580 * B, 320 * B, 584 * B, 318 * B) == 1
    assert _dq(10 * B, 320 * B, 584 * B, 318 * B) == 2  # 1/58: warning as before


def test_switch_off_restores_dq3(monkeypatch):
    monkeypatch.setattr(build, "_R339_LOW_REVENUE_ASSETS_NORMAL", False)
    assert _dq(612_436_467, 318 * B, 584 * B, 318 * B) == 3


def test_helper_bounds():
    assert _r339_low_revenue_is_real(0.001, 1.0)
    assert not _r339_low_revenue_is_real(0.001, 31.0)
    assert not _r339_low_revenue_is_real(0.001, 1 / 31)
    assert not _r339_low_revenue_is_real(500.0, 1.0)
    assert not _r339_low_revenue_is_real(0.001, None)
