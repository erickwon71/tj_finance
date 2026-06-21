"""Track C(PDF) 파서 단위 테스트 — 텍스트-리전 파싱(앵커·단위·컬럼·매핑).

실행: python -m fin2.tests.test_pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.pdf import (  # noqa: E402
    parse_number, _find_anchors, facts_from_text,
)

# 모던 보고서 모사: 연결 BS(천원) + 연결 IS(천원, interim 3개월·누적) + 별도 BS.
_MODERN = """2. 연결재무제표
2-1. 연결 재무상태표
연결 재무상태표
제 50 기 1분기말 2026.03.31 현재
(단위 : 천원)
자산
유동자산 32,208,963 30,705,420
자산총계 56,659,594 53,953,669
부채총계 39,219,529 37,000,000
자본총계 17,440,065 16,953,669
2-2. 연결 손익계산서
연결 손익계산서
제 50 기 2026.01.01 ~ 2026.03.31
(단위 : 천원)
3개월 누적 3개월 누적
매출 5,000,000 5,000,000 4,800,000 4,800,000
영업이익 600,000 600,000 500,000 500,000
당기순이익 500,000 500,000 400,000 400,000
4. 재무제표
재무상태표
제 50 기 1분기말 2026.03.31 현재
(단위 : 천원)
자산총계 26,535,096 25,000,000
부채총계 17,268,806 16,000,000
자본총계 9,266,290 9,000,000
"""


def _facts():
    return facts_from_text(_MODERN, corp_code="00000000", rcept_no="r",
                           report_fiscal_year=2026, report_fiscal_period="Q1")


def test_parse_number():
    assert parse_number("1,234,567") == 1234567
    assert parse_number("(1,234)") == -1234
    assert parse_number("△500") == -500
    assert parse_number("") is None
    assert parse_number("주5,6") == 56  # 숫자만 — 라벨 분리는 호출측 책임


def test_anchors_detected_with_basis_and_unit():
    ancs = _find_anchors(_MODERN)
    kinds = [(a.statement, a.basis, a.unit) for a in ancs]
    assert ("BS", "consolidated", 1000) in kinds
    assert ("IS", "consolidated", 1000) in kinds
    assert ("BS", "separate", 1000) in kinds


def test_bs_unit_scaling_and_identity():
    facts = _facts()
    def won(canon, basis):
        m = [f.amount_won for f in facts if f.canonical_account == canon and f.basis == basis]
        return m[0] if m else None
    # 천원 → 원(×1000)
    assert won("bs.total_assets", "consolidated") == 56_659_594_000
    # 회계 항등식: 자산 = 부채 + 자본
    assert won("bs.total_assets", "consolidated") == \
        won("bs.total_liabilities", "consolidated") + won("bs.total_equity", "consolidated")
    # 별도도 추출
    assert won("bs.total_assets", "separate") == 26_535_096_000


def test_interim_cumulative_column_selected():
    # interim IS '3개월 누적' 2단 → 누적(2번째) 컬럼 채택. 여기선 3개월==누적이라 값 동일하나
    # 컬럼 인덱스 선택 로직이 첫 전기 컬럼(4,800,000)으로 새지 않는지 검증.
    facts = _facts()
    rev = [f.amount_won for f in facts if f.canonical_account == "is.revenue"]
    assert 5_000_000_000 in rev


def test_unmapped_label_skipped():
    facts = facts_from_text(
        "재무상태표\n제 1 기 2020.12.31 현재\n(단위 : 원)\n"
        "자산총계 100\n부채총계 60\n자본총계 40\n알수없는계정 999\n",
        corp_code="c", rcept_no="r", report_fiscal_year=2020, report_fiscal_period="FY")
    canons = {f.canonical_account for f in facts}
    assert "bs.total_assets" in canons
    assert not any(c and c.startswith("unknown") for c in canons)


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
