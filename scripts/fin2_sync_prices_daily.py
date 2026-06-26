"""주가 데이터 확충 — 활성 보통주 전수 일별 OHLCV 수집.

pykrx get_market_ohlcv_by_date(티커당 1콜로 전 기간) 로 상장~현재 일별 시계열(시/고/저/종/거래량)을
stock_prices 에 멱등 적재. 재무(std_v2 / calendar_financials)와 corporations.stock_code 로 조인 가능한 토대.

⚠ 시총·펀더멘탈은 미수집: KRX market_cap/fundamental 엔드포인트가 pykrx 최신판에서도 구조적
breakage(빈 응답). 해당 지표는 후속 '재무↔주가 결합' 단계에서 검증 재무 DB로 파생한다.

선행: 없음(독립). 장시간(2,557 티커 × 1 API콜) → 사용자 직접 실행 권장(샤딩).

usage:
  python scripts/fin2_sync_prices_daily.py --limit 5                  # 파일럿
  python scripts/fin2_sync_prices_daily.py --stock 005930            # 단일 종목
  python scripts/fin2_sync_prices_daily.py --shard 0/4 --resume-file /tmp/px_0.txt
  python scripts/fin2_sync_prices_daily.py --since 2015              # start floor
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from analyzer.price_fetcher import sync_corp_daily

# pykrx 가 상장일부터만 반환하므로 와이드 start 는 무해(over-ask). 기본 = 사실상 전체 이력.
_DEFAULT_START = "19950101"


def _fetch_targets(since_year: int | None):
    """(corp_code, stock_code) 활성 보통주 — corp_code ASC."""
    sql = ("SELECT corp_code, stock_code FROM corporations "
           "WHERE is_active AND stock_code IS NOT NULL AND stock_code <> '' "
           "ORDER BY corp_code")
    with get_session() as s:
        return [(r[0], r[1]) for r in s.execute(text(sql))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="병렬 샤딩 I/N")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    ap.add_argument("--since", type=int, help="start floor 연도(기본=전체 이력)")
    ap.add_argument("--stock", help="단일 종목코드(6자리)")
    ap.add_argument("--corp", help="단일 corp_code(8자리)")
    ap.add_argument("--sleep", type=float, default=0.4, help="티커간 politeness sleep(초)")
    args = ap.parse_args()

    start = f"{args.since}0101" if args.since else _DEFAULT_START
    end = date.today().strftime("%Y%m%d")

    # 단일 종목 모드
    if args.stock or args.corp:
        if args.stock:
            targets = [(args.corp or "?", args.stock)]
        else:
            with get_session() as s:
                row = s.execute(text(
                    "SELECT corp_code, stock_code FROM corporations WHERE corp_code=:c"),
                    {"c": args.corp}).fetchone()
            if not row or not row[1]:
                logger.error(f"corp {args.corp} 종목코드 없음")
                return
            targets = [(row[0], row[1])]
    else:
        targets = _fetch_targets(args.since)
        if args.shard:
            i, n = (int(x) for x in args.shard.split("/"))
            targets = targets[i::n]
        done = set()
        if args.resume_file and Path(args.resume_file).exists():
            done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
        targets = [t for t in targets if t[0] not in done]
        if args.limit:
            targets = targets[:args.limit]

    total = len(targets)
    logger.info(f"[sync-prices-daily] 대상 {total} 종목, 기간 {start}~{end}")
    agg = {"rows": 0, "ok": 0, "empty": 0, "err": 0}

    for idx, (corp, stock) in enumerate(targets, 1):
        try:
            n = sync_corp_daily(stock, start, end)
            agg["rows"] += n
            if n > 0:
                agg["ok"] += 1
            else:
                agg["empty"] += 1
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[sync-prices-daily] corp={corp} stock={stock} 실패: {type(e).__name__}: {e}")
        if idx % 50 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} 행 {agg['rows']:,} ok {agg['ok']} empty {agg['empty']} 오류 {agg['err']}")
        if args.sleep and idx < total:
            time.sleep(args.sleep)

    logger.success(
        f"[sync-prices-daily] 완료 — 종목 {total}, 행 {agg['rows']:,}, "
        f"ok {agg['ok']}, empty {agg['empty']}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
