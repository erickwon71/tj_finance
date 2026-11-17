"""재무↔주가 결합 — 일별 시가총액 적재 (그날 실제 종가 × 그날 유통주식수).

★2026-11-17 (사용자 결정, 방식 B): 예전 식은 `close_price × current_shares` 였다.
  current_shares = 최신 사업보고서(FY)의 유통주식수 하나를 전 기간에 곱하는 상수였고, close_price 는
  "수정주가"라고 가정했다. 두 가정이 다 틀렸다:
  · 최신 FY 이후 주식수가 바뀐 회사(2025 FY 대비 30% 넘게 바뀐 회사 307개사: 무상증자·액면병합·
    유상증자)는 지금 시총이 틀렸다 — 티앤엘(2026-08 1:1 무상증자)은 절반, 5:1 병합 회사는 5배.
  · 일일 수집은 최근 15일만 다시 받으므로 저장된 과거 가격은 대부분 받은 날의 실제 가격이고 일부
    구간만 나중에 수정주가로 다시 받았다(티앤엘 2025-12 약 4.8만 → 2026-01 약 2.4만 가짜 반토막,
    하루 +45%/-40% 초과 움직임 216종목 247회). 그래서 과거 시총 = 실제 가격 × 지금 주식수가 됐다.
  이제 KRX OpenAPI 일별 매매정보(`scripts/krx_daily_trade_sync.py`)의 그날 실제 종가(close_raw)와
  상장주식수(list_shares)로 계산한다:

    market_cap(d) = close_raw(d) × float_shares(d)
    float_shares(d) = round(list_shares(d) × float_ratio(d))
    float_ratio(d) = 그날 직전 정기보고서(period_end ≤ d, 없으면 가장 이른 보고서)의
                     float_shares ÷ shares_out (유통주식수 ÷ 보통주 Ⅳ, 1 이하)
  자기주식 "수"를 빼지 않고 "비율"을 곱한다: 분기 중간에 액면병합·분할·무상증자가 있으면 자기주식도
  같이 병합·분할·배정되므로, 옛 보고서의 자기주식 수를 새 상장주식수에서 빼면 병합 회사는 시총이
  0 근처로 떨어진다(2026-11-18 검증에서 확인: 032190·007460 등).

  R225(2026-10-05, 사용자 결정): 시총·주당지표의 주식수 = 유통주식수(자기주식 제외). KRX 가 주는
  시가총액(krx_mktcap)은 자기주식을 포함한 값이라 별도 컬럼에 그대로 둔다.
  무상증자 권리락일부터 신주 상장일까지(보통 2~3주)는 KRX 상장주식수가 옛 값이라 KRX 공식 시총과
  같은 방식으로 작게 잡힌다.

  KRX 일별 데이터가 없는 행(2015 이전, 수집 누락)은 예전 방식으로 남긴다: close_price × 가장 최근
  정기보고서(분기·반기 포함)의 유통주식수.

shares_out 컬럼 = 그날 유통주식수(위 float_shares(d)) — market_cap = close_raw × shares_out 항등.
close_price 는 수정주가 시계열(차트·수익률용)로 그대로 둔다.

선행: scripts/krx_daily_trade_sync.py (nightly_valuation_refresh.py 가 이 스크립트 전에 실행).

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

# float_ratio(d) step function per corp, from the periodic reports.
_TREASURY_SQL = """
CREATE TEMP TABLE _float_ratio ON COMMIT DROP AS
WITH r AS (
    SELECT corp_code, period_end,
           min(LEAST(float_shares::float8 / shares_out, 1.0)) AS float_ratio
    FROM std_financials_v3
    WHERE shares_out > 0 AND float_shares > 0 AND period_end IS NOT NULL
    GROUP BY corp_code, period_end
)
SELECT c.stock_code, r.float_ratio,
       CASE WHEN row_number() OVER w = 1 THEN DATE '1900-01-01' ELSE r.period_end END AS valid_from,
       COALESCE(lead(r.period_end) OVER w, DATE '9999-12-31') AS valid_to
FROM r JOIN corporations c ON c.corp_code = r.corp_code AND c.stock_code IS NOT NULL
WINDOW w AS (PARTITION BY r.corp_code ORDER BY r.period_end);
CREATE INDEX ON _float_ratio (stock_code, valid_from);
"""

_KRX_SQL = """
UPDATE stock_prices sp
SET shares_out = x.shares,
    market_cap = sp.close_raw::bigint * x.shares
FROM (
    SELECT sp2.stock_code, sp2.trade_date,
           round(sp2.list_shares * COALESCE(t.float_ratio, 1.0))::bigint AS shares
    FROM stock_prices sp2
    LEFT JOIN _float_ratio t ON t.stock_code = sp2.stock_code
         AND sp2.trade_date >= t.valid_from AND sp2.trade_date < t.valid_to
    WHERE sp2.close_raw IS NOT NULL AND sp2.list_shares > 0 {stock_filter2}
) x
WHERE sp.stock_code = x.stock_code AND sp.trade_date = x.trade_date
  AND (sp.shares_out IS DISTINCT FROM x.shares
       OR sp.market_cap IS DISTINCT FROM sp.close_raw::bigint * x.shares)
"""

# Days after the last KRX row of a stock (today's KRX data is published after the nightly run):
# carry the last listed share count forward for up to 30 days. close_price of the latest days
# equals the unadjusted close unless a corporate action happened in between, which the next
# night's KRX row then corrects.
_CARRY_SQL = """
UPDATE stock_prices sp
SET shares_out = x.shares,
    market_cap = sp.close_price::bigint * x.shares
FROM (
    SELECT sp2.stock_code, sp2.trade_date,
           round(k.list_shares * COALESCE(t.float_ratio, 1.0))::bigint AS shares
    FROM stock_prices sp2
    JOIN LATERAL (SELECT k.list_shares, k.trade_date FROM stock_prices k
                  WHERE k.stock_code = sp2.stock_code AND k.list_shares > 0
                    AND k.trade_date < sp2.trade_date AND k.trade_date >= sp2.trade_date - 30
                  ORDER BY k.trade_date DESC LIMIT 1) k ON true
    LEFT JOIN _float_ratio t ON t.stock_code = sp2.stock_code
         AND sp2.trade_date >= t.valid_from AND sp2.trade_date < t.valid_to
    WHERE sp2.close_raw IS NULL AND sp2.trade_date >= current_date - 30 {stock_filter2}
) x
WHERE sp.stock_code = x.stock_code AND sp.trade_date = x.trade_date
  AND (sp.shares_out IS DISTINCT FROM x.shares
       OR sp.market_cap IS DISTINCT FROM sp.close_price::bigint * x.shares)
"""

# Rows without KRX daily data: previous method, with the share count of the latest periodic
# report (quarter / half year included), not the latest annual report.
_FALLBACK_SQL = """
WITH cur AS (
    SELECT DISTINCT ON (corp_code) corp_code, float_shares AS shares
    FROM std_financials_v3
    WHERE float_shares > 0 AND period_end IS NOT NULL
    ORDER BY corp_code, period_end DESC, float_shares DESC
)
UPDATE stock_prices sp
SET shares_out = cur.shares,
    market_cap = sp.close_price::bigint * cur.shares
FROM corporations c
JOIN cur ON cur.corp_code = c.corp_code
WHERE c.stock_code = sp.stock_code
  AND (sp.close_raw IS NULL OR sp.list_shares IS NULL)
  {stock_filter}
  AND (sp.shares_out IS DISTINCT FROM cur.shares
       OR sp.market_cap IS DISTINCT FROM sp.close_price::bigint * cur.shares)
"""


def run(stock: str | None = None) -> int:
    """그날 실제 종가 × 그날 유통주식수 시총(market_cap)·shares_out 재계산. 반환=갱신 행수."""
    params = {"sc": stock} if stock else {}
    f1 = "AND sp.stock_code = :sc" if stock else ""
    f2 = "AND sp2.stock_code = :sc" if stock else ""
    logger.info(f"[market-cap] 그날 종가 × 그날 유통주식수 {'(stock=' + stock + ')' if stock else '(전수)'}")
    with get_session() as s:
        s.execute(text(_TREASURY_SQL))
        n_krx = s.execute(text(_KRX_SQL.format(stock_filter2=f2)), params).rowcount
        n_old = s.execute(text(_FALLBACK_SQL.format(stock_filter=f1)), params).rowcount
        n_carry = s.execute(text(_CARRY_SQL.format(stock_filter2=f2)), params).rowcount
        s.commit()
    logger.success(f"[market-cap] 완료 — KRX 일별 {n_krx:,} 행 · 최근 이월 {n_carry:,} 행 · "
                   f"예전 방식(KRX 없음) {n_old:,} 행 갱신")
    return n_krx + n_old + n_carry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", help="단일 종목코드(파일럿)")
    args = ap.parse_args()
    run(args.stock)


if __name__ == "__main__":
    main()
