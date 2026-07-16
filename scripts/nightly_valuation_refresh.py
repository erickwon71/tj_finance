"""A4a · 밸류에이션 파이프라인 야간 갱신 오케스트레이터 (collect 잡에서 분리).

`valuation_daily` matview refresh 는 원래 `collect_new.py` 의 마지막 단계 ⑥ 에만 매달려 있었다.
그런데 collect 잡은 단계 ① 에서 DART 일일한도 초과(`DartApiError [020]`)로 크래시하면 ⑥ 에 도달하지
못해 **matview 가 며칠씩 정체**된다(외부 평가 2026-07-15, valuation_daily 3주 정체). 이 스크립트는
그 갱신 사슬을 **DART 와 무관한(pykrx/Naver 기반) 독립 잡**으로 떼어낸다:

  ① 주가 증분 top-up  — 최근 N일 OHLCV 를 stock_prices 에 멱등 upsert (기본 15일, --skip-prices 로 생략)
  ② 시가총액 재계산   — 수정주가 × 최신 FY 상장주식수 → market_cap/shares_out (순수 SQL, 빠름)
  ③ matview refresh   — REFRESH MATERIALIZED VIEW CONCURRENTLY valuation_daily

각 단계는 서로 격리(try/except)되어, 한 단계가 실패해도 나머지는 **이미 신선한 데이터 위에서** 계속
진행한다. launchd `com.tjfinance.valuation`(deploy/launchd/) 로 매일 실행. DART 쿼터를 쓰지 않으므로
collect 잡 성공 여부·gapfill 쿼터 경합과 무관하게 안정적으로 돈다.

usage:
  python scripts/nightly_valuation_refresh.py                      # 전수(증분 주가 15일 + 시총 + refresh)
  python scripts/nightly_valuation_refresh.py --skip-prices        # 주가 생략(시총+refresh 만, 초고속)
  python scripts/nightly_valuation_refresh.py --price-lookback-days 30
  python scripts/nightly_valuation_refresh.py --limit 5            # 파일럿(주가 5종목만)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session


def _active_targets(limit: int | None = None) -> list[tuple[str, str]]:
    """(corp_code, stock_code) 활성 보통주 — corp_code ASC."""
    sql = ("SELECT corp_code, stock_code FROM corporations "
           "WHERE is_active AND stock_code IS NOT NULL AND stock_code <> '' "
           "ORDER BY corp_code")
    with get_session() as s:
        rows = [(r[0], r[1]) for r in s.execute(text(sql))]
    return rows[:limit] if limit else rows


def _sync_prices(lookback_days: int, limit: int | None, sleep: float) -> dict:
    """최근 lookback_days 일 OHLCV 를 전수 증분 upsert. sync_corp_daily 재사용(멱등)."""
    from analyzer.price_fetcher import sync_corp_daily

    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    targets = _active_targets(limit)
    total = len(targets)
    logger.info(f"[valuation] ① 주가 증분 top-up — {total} 종목, 기간 {start}~{end}")
    agg = {"rows": 0, "ok": 0, "empty": 0, "err": 0}
    for idx, (corp, stock) in enumerate(targets, 1):
        try:
            n = sync_corp_daily(stock, start, end)
            agg["rows"] += n
            agg["ok" if n > 0 else "empty"] += 1
        except Exception as e:  # noqa: BLE001 — per-ticker 격리(네트워크·상폐 등)
            agg["err"] += 1
            logger.warning(f"[valuation] 주가 corp={corp} stock={stock} 실패: {type(e).__name__}: {e}")
        if idx % 200 == 0 or idx == total:
            logger.info(f"    ..{idx}/{total} 행 {agg['rows']:,} ok {agg['ok']} "
                        f"empty {agg['empty']} 오류 {agg['err']}")
        if sleep and idx < total:
            time.sleep(sleep)
    logger.success(f"[valuation] ① 완료 — 행 {agg['rows']:,}, ok {agg['ok']}, "
                   f"empty {agg['empty']}, 오류 {agg['err']}")
    return agg


def _market_cap() -> int:
    """② 시가총액·shares_out 재계산(순수 SQL)."""
    from scripts.fin2_market_cap_daily import run as market_cap_run
    logger.info("[valuation] ② 시가총액 재계산")
    return market_cap_run()


def _refresh() -> None:
    """③ valuation_daily matview refresh. CONCURRENTLY 우선, 최초/실패 시 plain 폴백."""
    from scripts.refresh_valuation_daily import refresh
    logger.info("[valuation] ③ valuation_daily matview refresh")
    try:
        refresh(concurrent=True)
    except Exception as e:  # noqa: BLE001 — 데이터 없음 등 → plain 폴백
        logger.warning(f"[valuation] CONCURRENTLY 실패({type(e).__name__}) → plain REFRESH 재시도")
        refresh(concurrent=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prices", action="store_true", help="주가 증분 top-up 생략(시총+refresh 만)")
    ap.add_argument("--price-lookback-days", type=int, default=15, help="주가 증분 조회 창(일, 기본 15)")
    ap.add_argument("--limit", type=int, help="주가 대상 종목 제한(파일럿)")
    ap.add_argument("--sleep", type=float, default=0.3, help="티커간 politeness sleep(초)")
    args = ap.parse_args()

    t0 = time.monotonic()
    logger.info(f"===== 밸류에이션 야간 갱신 {date.today()} =====")
    failures: list[str] = []

    # ① 주가(선택) — 단계 격리
    if not args.skip_prices:
        try:
            _sync_prices(args.price_lookback_days, args.limit, args.sleep)
        except Exception as e:  # noqa: BLE001
            failures.append("prices")
            logger.error(f"[valuation] ① 주가 단계 실패(계속): {type(e).__name__}: {e}")
    else:
        logger.info("[valuation] ① 주가 top-up 생략(--skip-prices)")

    # ② 시가총액 — 단계 격리
    try:
        _market_cap()
    except Exception as e:  # noqa: BLE001
        failures.append("market_cap")
        logger.error(f"[valuation] ② 시총 단계 실패(계속): {type(e).__name__}: {e}")

    # ③ matview refresh — 단계 격리
    try:
        _refresh()
    except Exception as e:  # noqa: BLE001
        failures.append("refresh")
        logger.error(f"[valuation] ③ refresh 단계 실패: {type(e).__name__}: {e}")

    dt = time.monotonic() - t0
    if failures:
        logger.error(f"[valuation] 완료(일부 실패: {', '.join(failures)}) — {dt:,.1f}초")
        # refresh 실패만 게이트(밸류에이션 최신성 직결). 알림은 dq_nightly staleness 어서션이 담당.
        sys.exit(1 if "refresh" in failures else 0)
    logger.success(f"[valuation] 전 단계 완료 — {dt:,.1f}초")


if __name__ == "__main__":
    main()
