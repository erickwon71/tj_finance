"""
스크리너 데이터 로더.

Phase 3(단일패스): 최신 FY 기준 전체 모집단을 한 번 로드한다. 모집단 행은
`analyzer.screener.screen` 이 만드는 행과 **완전히 동일**(같은 compute_ratios·
멀티플·Piotroski 산식) — 필터를 비우고 한도를 해제해 전수를 받아온 뒤, 페이지에서
`analyzer.screener._check` 로 메모리 필터·정렬을 적용한다. 따라서 결과·정렬이
`python run.py screen ...` CLI 와 일치한다.

Phase 4 에서 `load_screening_window(n_years, fiscal_year)`(rn 캡 확장 + 윈도우 집계)
가 여기 추가된다.
"""
from __future__ import annotations

from typing import Optional

# 사실상 무한 한도 — 전수 모집단을 받기 위함(전체 활성 보통주 ~2.5천)
_NO_LIMIT = 1_000_000


def load_population(fiscal_year: Optional[int] = None) -> list[dict]:
    """
    필터 없는 전체 모집단(최신 FY, 연결, data_quality<3).

    반환 행 = `analyzer.screener.screen` 의 행 스키마와 동일:
      corp_code, corp_name, stock_code, market, fiscal_year, market_cap_jo,
      roe/roa/roic/op_margin/net_margin/ebitda_margin,
      per/pbr/ev_ebitda/pcr/psr,
      revenue_growth/op_growth/ni_growth,
      debt_ratio/current_ratio/interest_coverage, ccc,
      fcf_quality/accrual_ratio, piotroski
    """
    from analyzer.screener import screen

    return screen(
        filters={},
        market=None,
        sort_by="roe",
        sort_asc=False,
        limit=_NO_LIMIT,
        fiscal_year=fiscal_year,
    )
