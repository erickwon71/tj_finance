"""신규 공시 수집·DB화 (헤드리스) — 수집 페이지와 동일 흐름의 CLI 판.

실행일 기준 최근 N일 정기공시 탐지 → sync_filings(force) → 다운로드 → 파싱·표준화·분기·달력.
수동 실행하거나 cron/launchd 로 매일 예약할 수 있다.

실행:
  .venv_tj_finance/bin/python scripts/collect_new.py [--days 7]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="실행일로부터 최근 N일 정기공시 확인")
    args = ap.parse_args()

    from app.data import collect
    from collector.db import get_session
    from collector.downloader import run_downloads
    from collector.filing_collector import sync_filings
    from run import process_corp

    # ① 탐지
    disc = collect.discover_recent_corps(args.days)
    corps = disc["corps"]
    logger.info(f"[collect] ① 최근 {args.days}일({disc['window']}) 정기공시 "
                f"{disc['total_filings']}건 → 활성 보통주 {len(corps)}개 기업")
    if not corps:
        logger.success("[collect] 신규 공시 없음 — 종료")
        return

    # ② 공시목록 동기화(force: 기존 기업의 신규 공시 재확인)
    r1 = sync_filings(corp_codes=corps, force=True)
    logger.info(f"[collect] ② 동기화 {r1.get('processed', 0)}개 기업 (API {r1.get('api_calls', 0)}콜)")

    # ③ 다운로드
    r2 = run_downloads(only_corp_codes=corps)
    logger.info(f"[collect] ③ 다운로드 완료 {r2.get('completed', 0)} / 실패 {r2.get('failed', 0)} / "
                f"스킵 {r2.get('skipped', 0)} (큐 {r2.get('total_queued', 0)})")

    # ④ 파싱·표준화·분기·달력 (신규 기업만)
    affected = collect.needs_standardize_corps(only=corps)
    logger.info(f"[collect] ④ 파싱·표준화 대상 {len(affected)}개 기업")
    agg = {"e_facts": 0, "s": 0, "q": 0, "c": 0, "errors": 0}
    for i, corp in enumerate(affected, 1):
        try:
            with get_session() as session:
                out = process_corp(session, corp)
                for k in ("e_facts", "s", "q", "c"):
                    agg[k] += out[k]
                session.commit()
        except Exception as exc:  # noqa: BLE001
            agg["errors"] += 1
            logger.warning(f"[collect]   {corp} 실패: {exc}")
        if i % 20 == 0 or i == len(affected):
            logger.info(f"[collect]   진행 {i}/{len(affected)} (std_v2 {agg['s']:,}, 오류 {agg['errors']})")

    logger.success(f"[collect] 완료 — 신규 {len(corps)}개 기업 · fact {agg['e_facts']:,} · "
                   f"std_v2 {agg['s']:,} · 이산분기 {agg['q']:,} · 달력 {agg['c']:,} · 오류 {agg['errors']}")


if __name__ == "__main__":
    main()
