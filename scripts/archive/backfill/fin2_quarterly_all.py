"""PRD 03 §5.1 분기환산 전수 적용 — as-filed std_v2 에서 이산분기(Q1~Q4) 파생.

std_financials_v2 에 is_discrete=True 행을 채운다(누적행 불가침, 멱등 upsert).
재추출/재표준화 불요 — 기존 as-filed 누적행만 읽어 차감.

usage:
  python scripts/fin2_quarterly_all.py [--shard I/N] [--resume-file F] [--limit N]
8-way 병렬: --shard 0/8 ~ 7/8 (corp 정렬 후 i::N).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.standardize.quarterly import derive_quarters_corp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="병렬 샤딩 I/N")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=1 "
            "AND NOT COALESCE(is_discrete,false) ORDER BY corp_code"))]
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        corps = corps[i::n]
    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[:args.limit]
    logger.info(f"[quarterly-all] 대상 corp {len(corps)}")

    total = len(corps)
    agg = {"q": 0, "err": 0}
    for idx, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                agg["q"] += derive_quarters_corp(s, corp)
                s.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[quarterly-all] corp={corp} 실패: {type(e).__name__}: {e}")
        if idx % 200 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} 이산분기 {agg['q']:,} 오류 {agg['err']}")

    logger.success(f"[quarterly-all] 완료 — corp {total}, 이산분기 {agg['q']:,}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
