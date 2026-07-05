"""
app.compute.checks.financial_anomalies 회귀 테스트 (표시단계 이상치 가드, W8).

영업이익률 sanity(>100% 불가 / >60% 의심) + 매출·이익 급증(연간 전년 4배, 분기 전년동기
4배 AND 직전분기 1.8배) 트리거를 고정. 정상 시계열은 무경고여야 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compute.checks import financial_anomalies  # noqa: E402
from tests._util import run_tests  # noqa: E402


def test_margin_impossible():
    msgs = financial_anomalies([{"fiscal_year": 2024, "revenue": 100, "operating_income": 150}])
    assert any("초과" in m for m in msgs)


def test_margin_suspect():
    msgs = financial_anomalies([{"fiscal_year": 2024, "revenue": 100, "operating_income": 70}])
    assert any("비정상적으로 높음" in m for m in msgs)
    assert not any("초과" in m for m in msgs)   # 60~100% 는 의심만


def test_annual_yoy_spike():
    series = [{"fiscal_year": 2024, "revenue": 500, "operating_income": 50},
              {"fiscal_year": 2023, "revenue": 100, "operating_income": 40}]
    msgs = financial_anomalies(series, "annual")
    assert any("급증" in m and "매출" in m for m in msgs)   # 매출 5배
    assert not any("영업이익" in m and "급증" in m for m in msgs)  # 영업이익 1.25배 = 정상


def test_no_false_positive_on_steady_growth():
    series = [{"fiscal_year": 2024, "revenue": 110, "operating_income": 22},
              {"fiscal_year": 2023, "revenue": 100, "operating_income": 20}]
    assert financial_anomalies(series, "annual") == []


def test_quarter_needs_dual_trigger():
    # 전년 동기 대비 5배지만 직전 분기 대비 1.2배(<1.8) → 트리거 안 됨(계절 회복 배제)
    series = [
        {"calendar_year": 2024, "calendar_period": "CQ1", "revenue": 500},
        {"calendar_year": 2023, "calendar_period": "CQ4", "revenue": 420},
        {"calendar_year": 2023, "calendar_period": "CQ1", "revenue": 100},
    ]
    assert not any("급증" in m for m in financial_anomalies(series, "quarter"))

    # 전년 동기 5배 AND 직전 분기 2.5배 → 트리거
    series2 = [
        {"calendar_year": 2024, "calendar_period": "CQ1", "revenue": 500},
        {"calendar_year": 2023, "calendar_period": "CQ4", "revenue": 200},
        {"calendar_year": 2023, "calendar_period": "CQ1", "revenue": 100},
    ]
    assert any("급증" in m for m in financial_anomalies(series2, "quarter"))


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
