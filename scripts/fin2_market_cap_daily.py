"""재무↔주가 결합 — 일별 시가총액 적재 (액면분할 등 보정 반영).

★ stock_prices.close_price 는 pykrx get_market_ohlcv_by_date(adjusted=True 기본)로 수집한
**KRX 수정주가**(액면분할·무상증자·유상증자 등 주식수 변동을 현재 기준으로 back-adjust)다.
따라서 시가총액은 **수정주가 × 현재(최신) 상장주식수** 로 계산해야 전 기간 일관·정확하다.
(분할 이전 가격은 KRX 가 이미 현재 주식수 기준으로 나눠놓았으므로 현재 주식수를 곱하면
그 시점 실제 시총이 복원되고, 가격 자체도 현재 주식수 기준으로 비교가능해진다.)

  market_cap(d) = close_price(d) × current_shares     # close_price = 수정주가
  current_shares = 해당 corp 최신 FY 의 shares_out (DART 백필)

shares_out 컬럼에는 이 current_shares(현재 기준 주식수, 상수)를 적재 → market_cap=close×shares_out
항등 유지. 실제 연도별 actual 주식수는 std_financials_v2.shares_out 에 보존.

선행: fin2_backfill_shares.py (최신 FY shares 확보). 멱등·순수 SQL.

usage:
  python scripts/fin2_market_cap_daily.py              # 전수
  python scripts/fin2_market_cap_daily.py --stock 005930   # 단일(파일럿)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# current_shares = corp 의 최신 FY(shares 보유) 의 상장주식수(con/sep 동일 → max).
# market_cap = 수정주가(close) × current_shares.
_SQL = """
WITH cur AS (
    SELECT f.corp_code, max(f.shares_out) AS shares
    FROM std_financials_v2 f
    JOIN (
        SELECT corp_code, max(fiscal_year) AS myr
        FROM std_financials_v2
        WHERE fiscal_period = 'FY' AND version = 1 AND shares_out > 0
          AND NOT COALESCE(is_discrete, false) AND NOT COALESCE(is_stub, false)
        GROUP BY corp_code
    ) m ON m.corp_code = f.corp_code AND m.myr = f.fiscal_year
    WHERE f.fiscal_period = 'FY' AND f.version = 1 AND f.shares_out > 0
    GROUP BY f.corp_code
)
UPDATE stock_prices sp
SET shares_out = cur.shares,
    market_cap = sp.close_price::bigint * cur.shares
FROM corporations c
JOIN cur ON cur.corp_code = c.corp_code
WHERE c.stock_code = sp.stock_code
  {stock_filter}
  AND (sp.shares_out IS DISTINCT FROM cur.shares
       OR sp.market_cap IS DISTINCT FROM sp.close_price::bigint * cur.shares)
"""


def run(stock: str | None = None) -> int:
    """수정주가×현재주식수 시총(market_cap)·shares_out 재계산. 반환=갱신 행수. 멱등·순수 SQL."""
    stock_filter = "AND sp.stock_code = :sc" if stock else ""
    params = {"sc": stock} if stock else {}
    sql = _SQL.format(stock_filter=stock_filter)

    logger.info(f"[market-cap] 수정주가×현재주식수 시총 계산 "
                f"{'(stock=' + stock + ')' if stock else '(전수)'}")
    with get_session() as s:
        res = s.execute(text(sql), params)
        logger.success(f"[market-cap] 완료 — {res.rowcount:,} 행 갱신")
        return res.rowcount


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", help="단일 종목코드(파일럿)")
    args = ap.parse_args()
    run(args.stock)


if __name__ == "__main__":
    main()
