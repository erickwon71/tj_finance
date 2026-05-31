"""
concept_map.map_acode 단위 테스트 (DB 비의존).

검증: 핵심 표준 개념 매핑 정확성, canonical 네임스페이스 유효성, 미등록→None.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.taxonomy.concept_map import map_acode, ACODE_TO_CANONICAL  # noqa: E402


def test_core_bs_is_cf():
    assert map_acode("ifrs-full_Assets") == "bs.total_assets"
    assert map_acode("ifrs-full_Equity") == "bs.total_equity"
    assert map_acode("ifrs-full_Liabilities") == "bs.total_liabilities"
    assert map_acode("ifrs-full_Revenue") == "is.revenue"
    assert map_acode("ifrs-full_ProfitLoss") == "is.net_income"
    assert map_acode("ifrs-full_CashFlowsFromUsedInOperatingActivities") == "cf.operating"


def test_dart_extension_codes():
    # dart_* 확장 코드도 동일 canonical 로 수렴
    assert map_acode("dart_OperatingIncomeLoss") == "is.operating_income"
    assert map_acode("dart_CapitalSurplus") == "bs.capital_surplus"
    assert map_acode("dart_ShortTermTradePayables") == "bs.trade_payables"


def test_both_tracks_share_namespace():
    # 모든 canonical 은 bs./is./cf. 네임스페이스(텍스트 트랙과 동일)
    for code in ACODE_TO_CANONICAL.values():
        assert code.split(".")[0] in ("bs", "is", "cf"), code


def test_unmapped_returns_none():
    assert map_acode("ifrs-full_EquityAndLiabilities") is None  # 합계중복 → 의도적 미매핑
    assert map_acode("dart_EquityAtBeginningOfPeriod") is None  # SCE 전용
    assert map_acode("ifrs-full_SomethingUnknown") is None
    assert map_acode(None) is None


def test_statement_prefix_consistency():
    # CF 흐름 개념이 실수로 bs./is. 로 가지 않는지(접두어 일관성)
    assert map_acode("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities") == "cf.capex"
    assert map_acode("ifrs-full_DividendsPaidClassifiedAsFinancingActivities") == "cf.dividends_paid"


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
