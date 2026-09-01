"""calendar_v3.py 단위 테스트 — std_financials_v3 소스 로더(_load_asfiled_v3)가 새로
추가한 배선(basis 필터, is_ifrs 상수화)을 실DB 없이 스텁 세션으로 검증한다.

이산분기 조립(_build_discrete)·달력 레코드 조립(_cq_record/_cy_record) 자체는 이 모듈이
그대로 재사용하는 기존 순수 함수라 test_quarterly.py/test_calendar.py 가 이미 커버 —
`calendarize_corp_v3()` 의 전체 파이프라인(오케스트레이션)은 실DB 표본검증(Phase 2)에서
확인한다.

실행: python -m fin2.tests.test_calendar_v3
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.standardize.calendar_v3 import _load_asfiled_v3  # noqa: E402


class _Row:
    """session.execute(...).fetchall() 이 반환하는 Row 흉내(._mapping 만 필요)."""
    def __init__(self, d: dict):
        self._mapping = d


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


def _v3_row(fy, fp, pe_month, pe_year, basis="consolidated", **vals):
    base = {
        "corp_code": "00000000", "fiscal_year": fy, "fiscal_period": fp,
        "statement_type": basis, "period_end": date(pe_year, pe_month, 31),
        "revenue": None, "net_income": None, "cfo": None,
        "total_assets": None, "total_equity": None,
    }
    base.update(vals)
    return base


class _FakeSession:
    """SELECT std_financials_v3 만 지원 — _load_asfiled_v3 전용 스텁."""

    def __init__(self, v3_rows: list[dict]):
        self._v3_rows = v3_rows

    def execute(self, clause, params: dict | None = None):
        sql = str(clause).strip()
        assert sql.startswith("SELECT * FROM std_financials_v3"), sql[:80]
        basis = params["b"]
        rows = [_Row(r) for r in self._v3_rows if r["statement_type"] == basis]
        return _Result(rows)


def test_keys_by_fy_fp_and_forces_is_ifrs_true():
    rows = [_v3_row(2024, "Q1", 3, 2024, revenue=100)]
    out = _load_asfiled_v3(_FakeSession(rows), "00000000", "consolidated")
    assert (2024, "Q1") in out
    assert out[(2024, "Q1")]["is_ifrs"] is True   # v3 엔 컬럼이 없어 상수로 채움(관례)
    assert out[(2024, "Q1")]["revenue"] == 100


def test_filters_by_basis():
    rows = [
        _v3_row(2024, "Q1", 3, 2024, basis="consolidated", revenue=100),
        _v3_row(2024, "Q1", 3, 2024, basis="separate", revenue=999),
    ]
    out = _load_asfiled_v3(_FakeSession(rows), "00000000", "consolidated")
    assert len(out) == 1
    assert out[(2024, "Q1")]["revenue"] == 100


def test_returns_empty_dict_when_no_rows():
    out = _load_asfiled_v3(_FakeSession([]), "00000000", "consolidated")
    assert out == {}


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
