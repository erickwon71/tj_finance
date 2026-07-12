"""배당 지표 카탈로그 — Phase 2(PRD 13) 차트빌더 노출. dividend_facts 소스.

EXTENDED_CATALOG(fact_v2 기반 확장 재무항목)와 별개 테이블(dividend_facts, 이미 corp+fy 당
1행 피벗)이라 같은 카탈로그에 섞지 않고 별도 파일로 둔다. PCT 단위는 다른 PCT 지표와 동일하게
소수(0.678) 축약 관례를 따르므로, app/compute/sources.py::fetch_dividend_frame 에서 100 으로
나눠 변환한다(원본 dividend_facts.payout_ratio 는 이미 %스케일 67.8).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.registry.units import UnitType


@dataclass(frozen=True)
class DividendSpec:
    id: str
    name_ko: str
    unit: UnitType


DIVIDEND_CATALOG: list[DividendSpec] = [
    DividendSpec("div.dps_common", "주당 현금배당금(보통주)", UnitType.WON_PER_SHARE),
    DividendSpec("div.payout_ratio", "배당성향", UnitType.PCT),
    DividendSpec("div.dividend_yield_common", "현금배당수익률", UnitType.PCT),
    DividendSpec("div.total_dividend_amount", "배당총액", UnitType.AMOUNT_EOK),
]

DIVIDEND_BY_ID: dict[str, DividendSpec] = {s.id: s for s in DIVIDEND_CATALOG}
