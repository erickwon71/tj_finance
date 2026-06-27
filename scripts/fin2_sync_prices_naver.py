"""주가 심화 이력 — Naver Finance siseJson 으로 상장~현재 일별 OHLCV 수집.

pykrx/koapy 가 pre-2014 를 못 줘서(2014 floor / KRX MDCSTAT LOGOUT) Naver siseJson 으로 대체 수집.
Naver 는 **수정주가**(액면분할 보정, 현재 기준) 를 상장일까지 제공 → 기존 pykrx 수집(2014+)과 동일
basis 라 그대로 덮어쓰며 pre-2014 확장. 상장주식수·시총 미제공 → fin2_market_cap_daily 로 파생.

⚠ 네트워크가 막힌 환경(샌드박스)에선 동작 안 함 → 사용자 Mac 에서 실행.

usage:
  python scripts/fin2_sync_prices_naver.py --stock 005930          # 단일(검증)
  python scripts/fin2_sync_prices_naver.py --limit 5
  python scripts/fin2_sync_prices_naver.py --shard 0/4 --resume-file /tmp/nv_0.txt
  python scripts/fin2_sync_prices_naver.py --since 1990            # start floor(기본 1990)
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
from analyzer.price_fetcher import sync_corp_daily_naver

_DEFAULT_START = "19900101"  # Naver 는 상장일부터만 반환 → 와이드 start 무해


def _fetch_targets():
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
    ap.add_argument("--since", type=int, help="start floor 연도(기본 1990=상장 전체)")
    ap.add_argument("--stock", help="단일 종목코드")
    ap.add_argument("--sleep", type=float, default=0.3, help="티커간 politeness sleep(초)")
    args = ap.parse_args()

    start = f"{args.since}0101" if args.since else _DEFAULT_START
    end = date.today().strftime("%Y%m%d")

    if args.stock:
        targets = [("?", args.stock)]
    else:
        targets = _fetch_targets()
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
    logger.info(f"[naver-prices] 대상 {total} 종목, 기간 {start}~{end}")
    agg = {"rows": 0, "ok": 0, "empty": 0, "err": 0}

    for idx, (corp, stock) in enumerate(targets, 1):
        try:
            n = sync_corp_daily_naver(stock, start, end)
            agg["rows"] += n
            agg["ok" if n > 0 else "empty"] += 1
            if args.resume_file and corp != "?":
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[naver-prices] corp={corp} stock={stock} 실패: {type(e).__name__}: {e}")
        if idx % 50 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} 행 {agg['rows']:,} ok {agg['ok']} empty {agg['empty']} 오류 {agg['err']}")
        if args.sleep and idx < total:
            time.sleep(args.sleep)

    logger.success(f"[naver-prices] 완료 — 종목 {total}, 행 {agg['rows']:,}, "
                   f"ok {agg['ok']}, empty {agg['empty']}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
