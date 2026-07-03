"""밸류에이션 밴드 로더 — valuation_daily 일별 멀티플 시계열.

'자기 역사 대비 싸다/비싸다'를 보여주기 위해 일별 PER/PBR/배당수익률 등 멀티플의 과거 분포와
현재 위치(백분위)를 계산한다. valuation_daily(주가×재무 파생)를 소비. UI 비의존.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text

from collector.db import get_session

# 표시 가능한 멀티플: key(컬럼 화이트리스트) → (라벨, 퍼센트표시 여부)
BAND_METRICS: dict[str, tuple[str, bool]] = {
    "per": ("PER", False),
    "pbr": ("PBR", False),
    "psr": ("PSR", False),
    "ev_ebitda": ("EV/EBITDA", False),
    "dividend_yield": ("배당수익률", True),
}


def load_valuation_series(
    corp_code: str, metric: str, since_year: Optional[int] = None
) -> list[dict]:
    """corp 의 일별 멀티플 시계열(오름차순, non-null). [{trade_date, value}, ...]."""
    if metric not in BAND_METRICS:
        raise ValueError(f"metric must be one of {list(BAND_METRICS)}, got {metric!r}")
    date_clause = "AND trade_date >= :d" if since_year else ""
    sql = text(f"""
        SELECT trade_date, {metric} AS value
        FROM valuation_daily
        WHERE corp_code = :c AND {metric} IS NOT NULL {date_clause}
        ORDER BY trade_date
    """)
    params: dict = {"c": corp_code}
    if since_year:
        params["d"] = date(since_year, 1, 1)
    with get_session() as s:
        return [{"trade_date": r[0], "value": float(r[1])}
                for r in s.execute(sql, params).fetchall()]


def band_stats(values: list[float]) -> Optional[dict]:
    """분포 통계 + 현재값 백분위. 현재=마지막(최신) 값 가정은 호출자 책임(정렬된 시계열)."""
    if not values:
        return None
    xs = sorted(values)
    n = len(xs)

    def pct(p: float) -> float:
        # 선형보간 백분위
        if n == 1:
            return xs[0]
        idx = p / 100 * (n - 1)
        lo = int(idx)
        frac = idx - lo
        hi = min(lo + 1, n - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * frac

    cur = values[-1]
    # 현재값의 백분위 순위(현재보다 작은 값의 비율)
    rank = sum(1 for v in xs if v < cur) / n * 100
    return {
        "current": cur,
        "min": xs[0], "p10": pct(10), "p25": pct(25), "median": pct(50),
        "p75": pct(75), "p90": pct(90), "max": xs[-1],
        "percentile": rank, "n": n,
    }
