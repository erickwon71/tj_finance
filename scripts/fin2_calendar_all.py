"""PRD 03 §5.3 Layer 2 달력정규화 전수 적용 — 이산분기 → std_financials_calendar.

이산분기(is_discrete) period_end 를 달력분기/연도로 재배열·합산. 멱등 upsert.
선행: 분기환산(§5.1, fin2_quarterly_all.py) 완료 필요.

usage:
  python scripts/fin2_calendar_all.py [--shard I/N] [--resume-file F] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.standardize.calendar import calendarize_corp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="병렬 샤딩 I/N")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM std_financials_v2 "
            "WHERE is_discrete=true ORDER BY corp_code"))]
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        corps = corps[i::n]
    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[:args.limit]
    logger.info(f"[calendar-all] 대상 corp {len(corps)}")

    total = len(corps)
    agg = {"c": 0, "err": 0}
    for idx, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                agg["c"] += calendarize_corp(s, corp)
                s.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[calendar-all] corp={corp} 실패: {type(e).__name__}: {e}")
        if idx % 200 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} 달력행 {agg['c']:,} 오류 {agg['err']}")

    logger.success(f"[calendar-all] 완료 — corp {total}, 달력행 {agg['c']:,}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
