"""재무↔주가 결합 키스톤 — 상장주식수 전체 이력 백필 (DART stockTotqySttus).

밸류에이션 멀티플(시총·PER·PBR·EPS·BPS)의 핵심은 상장주식수인데 std_financials_v2.shares_out 은
sparse(과거 DART 수집분 ~29%)다. DART stockTotqySttus(get_shares_from_dart, 보통주)로 FY 결산 주식수를
전 연도 백필한다.

각 (corp, fiscal_year) 결측건에 대해:
  1) std_financials_v2.shares_out UPDATE (해당 corp+fy 의 FY 행 — consolidated·separate 양쪽,
     주식수는 실체 단위라 동일)
  2) stock_prices.shares_out 에 그 FY period_end 최근접 거래일로 seed (_shares_out 소스 일관 →
     향후 재표준화가 백필을 덮지 않게 함)

DART 일쿼터(20K) → 사용자 직접 실행(장시간). 결측(해당연도 보고서 없음)은 NULL 유지(부분 커버 허용).

usage:
  python scripts/fin2_backfill_shares.py --corp 00126380          # 단일(파일럿)
  python scripts/fin2_backfill_shares.py --shard 0/4 --resume-file /tmp/sh_0.txt
  python scripts/fin2_backfill_shares.py --limit 100
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from analyzer.price_fetcher import get_shares_from_dart


def _targets(corp: str | None, fy_min: int):
    """주식수 결측 (corp_code, fiscal_year, period_end, stock_code) — FY 행 기준.

    fy_min: DART stockTotqySttus 는 구조화 API 라 ~2016+ 만 데이터 보유(이전은 istc_totqy='-').
    기본 2016 으로 막아 불가능한 과거 연도에 쿼터를 낭비하지 않는다.
    """
    where = "AND f.corp_code = :corp" if corp else ""
    sql = f"""
        SELECT f.corp_code, f.fiscal_year, max(f.period_end) AS period_end, c.stock_code
        FROM std_financials_v2 f
        JOIN corporations c ON c.corp_code = f.corp_code
        WHERE f.version = 1 AND f.fiscal_period = 'FY'
          AND NOT COALESCE(f.is_discrete, false) AND NOT COALESCE(f.is_stub, false)
          AND (f.shares_out IS NULL OR f.shares_out = 0)
          AND f.fiscal_year >= :fy_min
          AND c.stock_code IS NOT NULL AND c.stock_code <> ''
          {where}
        GROUP BY f.corp_code, f.fiscal_year, c.stock_code
        ORDER BY f.corp_code, f.fiscal_year
    """
    params = {"corp": corp, "fy_min": fy_min} if corp else {"fy_min": fy_min}
    with get_session() as s:
        return [(r[0], r[1], r[2], r[3]) for r in s.execute(text(sql), params)]


def _apply(corp_code: str, fiscal_year: int, period_end, stock_code: str, shares: int) -> None:
    with get_session() as s:
        s.execute(text("""
            UPDATE std_financials_v2 SET shares_out = :n
            WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = 'FY'
              AND version = 1 AND (shares_out IS NULL OR shares_out = 0)
        """), {"n": shares, "c": corp_code, "y": fiscal_year})
        # seed stock_prices at the FY period_end 최근접 거래일 (forward-fill 기준점)
        if period_end:
            s.execute(text("""
                UPDATE stock_prices SET shares_out = :n
                WHERE stock_code = :sc AND trade_date = (
                    SELECT max(trade_date) FROM stock_prices
                    WHERE stock_code = :sc AND trade_date <= :pe)
            """), {"n": shares, "sc": stock_code, "pe": period_end})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="병렬 샤딩 I/N")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    ap.add_argument("--corp", help="단일 corp_code")
    ap.add_argument("--fy-min", type=int, default=2016,
                    help="이 연도 이상만(DART stockTotqySttus 가용 하한, 기본 2016)")
    ap.add_argument("--sleep", type=float, default=0.1, help="DART 콜간 sleep(초)")
    args = ap.parse_args()

    targets = _targets(args.corp, args.fy_min)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        targets = targets[i::n]
    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    targets = [t for t in targets if f"{t[0]}:{t[1]}" not in done]
    if args.limit:
        targets = targets[:args.limit]

    total = len(targets)
    logger.info(f"[backfill-shares] 결측 (corp,fy) {total}건")
    agg = {"found": 0, "miss": 0, "err": 0}

    for idx, (corp, fy, period_end, stock) in enumerate(targets, 1):
        key = f"{corp}:{fy}"
        try:
            shares = get_shares_from_dart(corp, fy)
            if shares and shares > 0:
                _apply(corp, fy, period_end, stock, shares)
                agg["found"] += 1
            else:
                agg["miss"] += 1
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(key + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[backfill-shares] {key} 실패: {type(e).__name__}: {e}")
        if idx % 200 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} found {agg['found']} miss {agg['miss']} 오류 {agg['err']}")
        if args.sleep:
            time.sleep(args.sleep)

    logger.success(
        f"[backfill-shares] 완료 — (corp,fy) {total}, found {agg['found']}, "
        f"miss {agg['miss']}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
