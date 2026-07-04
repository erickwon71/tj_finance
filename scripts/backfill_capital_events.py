"""job B · 자본이벤트(증자/감자/CB·BW·EB/자기주식) 전체 히스토리 백필.

sync_capital_events(bgn_de, end_de) 의 상세조회는 **end_de 기준 365일 lookback** 으로
고정된다(collector/dart_capital.py 상단 주석 참조 — DART 상세API가 "현재 최종상태" 1행만
반환하는 특성 때문에 넉넉한 lookback을 둔 설계). 그래서 2015~오늘을 한 번에 넣으면 최근
365일 이전 이벤트는 조용히 누락된다 — 반드시 연 단위(<=365일) 창으로 나눠 호출해야
각 창의 lookback 이 그 창의 시작일을 온전히 커버한다.

이 스크립트는 2015-01-01 ~ 오늘을 연 단위 창으로 나눠 순차 호출하고, 창별 결과를 로그로
남긴다(rcept_no 유니크 제약이라 재실행해도 멱등 — 중단 시 같은 명령 재실행하면 이미 저장된
rcept_no 는 ON CONFLICT DO NOTHING 으로 건너뛰고 이어서 진행됨).

usage:
  python scripts/backfill_capital_events.py                       # 2015-01-01 ~ 오늘, 전체
  python scripts/backfill_capital_events.py --start-year 2018      # 특정 연도부터
  python scripts/backfill_capital_events.py --sleep 5              # 창 사이 대기(초, DART 예의)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from collector.dart_capital import sync_capital_events


def _year_windows(start_year: int, end_date: date) -> list[tuple[str, str]]:
    """연 단위(<=365일) 창 목록. 마지막 창은 오늘까지."""
    windows = []
    cur = date(start_year, 1, 1)
    while cur <= end_date:
        win_end = min(date(cur.year, 12, 31), end_date)
        windows.append((cur.strftime("%Y%m%d"), win_end.strftime("%Y%m%d")))
        cur = date(cur.year + 1, 1, 1)
    return windows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--sleep", type=float, default=3.0, help="창 사이 대기(초)")
    args = ap.parse_args()

    today = date.today()
    windows = _year_windows(args.start_year, today)
    logger.info(f"[capital-backfill] {args.start_year}~{today.year} · {len(windows)}개 연간 창")

    total = 0
    for i, (bgn, end) in enumerate(windows, 1):
        logger.info(f"[capital-backfill] ({i}/{len(windows)}) {bgn}~{end}")
        try:
            n = sync_capital_events(bgn, end)
            total += n
            logger.info(f"  -> 신규 {n}건 (누적 {total})")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"  -> 실패(비치명적, 다음 창 계속): {type(exc).__name__}: {exc}")
        if i < len(windows):
            time.sleep(args.sleep)

    logger.success(f"[capital-backfill] 완료 — {len(windows)}개 창 · 신규 총 {total}건")


if __name__ == "__main__":
    main()
