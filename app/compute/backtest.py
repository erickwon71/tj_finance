"""스크리너 백테스트 (P2, 외부평가) — 현재 스크린 조건을 과거 시점에 적용해 forward 수익률 검증.

절차 (연간 리밸런스, FY 지연으로 lookahead 회피):
  각 코호트 연도 Y (start_year..end_year):
    - rebalance = (Y+1)-05-01 직전 최근 거래일. (FY Y 사업보고서는 익년 3월말 제출 → 5월 매수)
    - load_screening_window(year_max=Y) — 그 시점까지의 재무 윈도우.
    - as-of(리밸런스) 종가로 market_cap/close_price 오버라이드 → build_base_frame = 그 시점 멀티플.
    - run_quant_passes(base, passes) → 선정 종목(포트폴리오).
    - forward 수익률 = close(rebalance + h년)/close(rebalance) − 1  (h ∈ horizons).
    - 벤치마크 = 스크린 유니버스 전체 동일가중, 동일기간.
  코호트 평균으로 집계.

한계(UI 캡션 명시):
  - 재무는 **정정본 포함**(as-filed 아님) → 정정 lookahead 소지.
  - **가격 수익률**(배당 재투자 미반영).
  - 리밸런스+h 시점 가격이 없는 종목(상장폐지 등)은 해당 호라이즌에서 제외 → 경미한 생존편향.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text

from app.compute.screen_eval import build_base_frame, run_quant_passes
from app.data.screen_window import load_screening_window
from collector.db import get_session


def _asof_prices(session, as_of: date, lookback_days: int = 20) -> dict[str, int]:
    """as_of 직전(≤) 최근 거래일 종가 — {stock_code: close}. 창(window) 내 없으면 제외."""
    rows = session.execute(text("""
        SELECT DISTINCT ON (stock_code) stock_code, close_price
        FROM stock_prices
        WHERE trade_date <= :asof AND trade_date >= :lo AND close_price > 0
        ORDER BY stock_code, trade_date DESC
    """), {"asof": as_of, "lo": as_of - timedelta(days=lookback_days)}).fetchall()
    return {sc: cp for sc, cp in rows}


def _rebalance_date(year: int) -> date:
    """FY Y 매수 시점 — 익년 5월 1일(사업보고서 제출 후, lookahead 회피 버퍼)."""
    return date(year + 1, 5, 1)


def _mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def run_backtest(
    passes: list[dict],
    method: str,
    n_periods: int,
    market: Optional[str],
    include_missing: bool,
    start_year: int,
    end_year: int,
    horizons: tuple[int, ...] = (1, 3, 5),
    statement_type: str = "consolidated",
) -> dict:
    """스크린 조건의 과거 코호트별 forward 수익률. 반환 = {cohorts, summary, horizons, ...}."""
    today = date.today()
    cohorts: list[dict] = []

    for y in range(start_year, end_year + 1):
        rebal = _rebalance_date(y)
        if rebal > today:
            continue
        # 그 시점까지의 재무 윈도우
        window = load_screening_window(n_periods, statement_type=statement_type, year_max=y)
        if not window:
            continue

        with get_session() as s:
            asof_px = _asof_prices(s, rebal)
            # as-of 가격으로 market_cap 오버라이드(= close × 그 시점 shares_out)
            for cc, c in window.items():
                sc = c.get("stock_code")
                close = asof_px.get(sc)
                shares = (c["rows"][0].get("shares_out") if c.get("rows") else None)
                if close and shares:
                    c["close_price"] = close
                    c["market_cap"] = int(close) * int(shares)
                else:
                    c["close_price"] = None
                    c["market_cap"] = None

            base = build_base_frame(window, method, n_periods)
            if market:
                base = base[base["market"].astype(str).str.upper() == market.upper()]
            # 리밸런스 시점 가격 있는 종목만(그 시점 실제 매수 가능)
            valid_codes = set(asof_px.keys())
            base = base[base["stock_code"].isin(valid_codes)]
            if base.empty:
                continue

            selected, _counts = run_quant_passes(base, passes, include_missing=include_missing)
            sel_codes = [c for c in selected["stock_code"].tolist() if c in valid_codes]
            univ_codes = base["stock_code"].tolist()

            port_ret: dict[int, Optional[float]] = {}
            bench_ret: dict[int, Optional[float]] = {}
            for h in horizons:
                fwd_date = date(rebal.year + h, rebal.month, rebal.day)
                if fwd_date > today:
                    port_ret[h] = bench_ret[h] = None
                    continue
                fwd_px = _asof_prices(s, fwd_date)
                port_ret[h] = _mean([fwd_px[c] / asof_px[c] - 1
                                     for c in sel_codes if c in fwd_px and c in asof_px])
                bench_ret[h] = _mean([fwd_px[c] / asof_px[c] - 1
                                      for c in univ_codes if c in fwd_px and c in asof_px])

        cohorts.append({
            "year": y, "rebalance_date": rebal.isoformat(),
            "n_selected": len(sel_codes), "n_universe": len(univ_codes),
            "port": port_ret, "bench": bench_ret,
        })

    # 코호트 평균(호라이즌별, 값 있는 코호트만)
    summary_port: dict[int, Optional[float]] = {}
    summary_bench: dict[int, Optional[float]] = {}
    summary_n: dict[int, int] = {}
    for h in horizons:
        pv = [c["port"][h] for c in cohorts if c["port"].get(h) is not None]
        bv = [c["bench"][h] for c in cohorts if c["bench"].get(h) is not None]
        summary_port[h] = _mean(pv)
        summary_bench[h] = _mean(bv)
        summary_n[h] = len(pv)

    return {
        "horizons": list(horizons),
        "cohorts": cohorts,
        "summary": {"port": summary_port, "bench": summary_bench, "n_cohorts": summary_n},
    }
