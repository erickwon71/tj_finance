"""신규 공시 수집·DB화 (헤드리스) — 수집 페이지와 동일 흐름의 CLI 판.

실행일 기준 최근 N일 정기공시 탐지 → sync_filings(force) → 다운로드 → 파싱·표준화·분기·달력.
수동 실행하거나 cron/launchd 로 매일 예약할 수 있다.

④ 파싱·표준화는 **기업당 워커 프로세스 + 타임아웃**으로 처리한다: 대용량/병리 보고서
(예: 30MB iXBRL)에서 100% CPU 로 정체하는 기업을 `--timeout` 초 초과 시 강제 종료·스킵하고
다음 기업으로 넘어간다(C레벨 lxml 멈춤도 프로세스 kill 로 확실히 중단). 워커는 재사용하고
멈춘 경우에만 재생성하므로 정상 기업엔 오버헤드가 거의 없다.

실행:
  .venv_tj_finance/bin/python scripts/collect_new.py [--days 7] [--timeout 120]
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import queue as pyqueue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger


def _worker(in_q, out_q) -> None:
    """워커 프로세스: in_q 에서 corp 받아 process_corp 실행·커밋, 결과를 out_q 로.
    None 받으면 종료. (spawn 으로 모듈 재임포트되므로 함수는 모듈 레벨이어야 함)"""
    from collector.db import get_session
    from run import process_corp

    while True:
        corp = in_q.get()
        if corp is None:
            return
        try:
            with get_session() as session:
                out = process_corp(session, corp)
                session.commit()
            out_q.put(("ok", corp, out))
        except Exception as exc:  # noqa: BLE001
            out_q.put(("err", corp, str(exc)))


def _standardize_with_timeout(affected: list[str], timeout: int) -> dict:
    """기업당 워커+타임아웃으로 파싱·표준화. 타임아웃 초과 기업은 워커 kill 후 스킵."""
    ctx = mp.get_context("spawn")
    in_q, out_q = ctx.Queue(), ctx.Queue()
    worker = ctx.Process(target=_worker, args=(in_q, out_q), daemon=True)
    worker.start()

    agg = {"e_facts": 0, "s": 0, "q": 0, "c": 0, "errors": 0, "timeout": 0}
    skipped: list[str] = []
    total = len(affected)
    for i, corp in enumerate(affected, 1):
        in_q.put(corp)
        try:
            status, c, payload = out_q.get(timeout=timeout)
            if status == "ok":
                for k in ("e_facts", "s", "q", "c"):
                    agg[k] += payload[k]
            else:
                agg["errors"] += 1
                logger.warning(f"[collect]   {c} 실패: {payload}")
        except pyqueue.Empty:
            # timeout 초과 = 정체 기업 → 워커 강제종료 후 재생성(미커밋 트랜잭션은 롤백)
            agg["timeout"] += 1
            skipped.append(corp)
            logger.warning(f"[collect]   ⏱ {corp} {timeout}초 초과 → 강제 스킵·워커 재시작")
            worker.terminate()
            worker.join()
            in_q, out_q = ctx.Queue(), ctx.Queue()
            worker = ctx.Process(target=_worker, args=(in_q, out_q), daemon=True)
            worker.start()
        if i % 20 == 0 or i == total:
            logger.info(f"[collect]   진행 {i}/{total} "
                        f"(std_v2 {agg['s']:,}, 스킵 {agg['timeout']}, 오류 {agg['errors']})")

    in_q.put(None)
    worker.join(timeout=10)
    if worker.is_alive():
        worker.terminate()
    if skipped:
        logger.warning(f"[collect]   ⏱ 타임아웃 스킵 {len(skipped)}개: {', '.join(skipped)}")
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="실행일로부터 최근 N일 정기공시 확인")
    ap.add_argument("--timeout", type=int, default=120, help="기업당 파싱·표준화 타임아웃(초)")
    ap.add_argument("--standardize-only", action="store_true",
                    help="①②③ 건너뛰고 ④(파싱·표준화)만 — 다운로드는 됐는데 표준화 남은 전체 기업 대상. 중단 후 재개용")
    args = ap.parse_args()

    from app.data import collect

    # ── 재개 모드: ④만 (이미 다운로드된 표준화 미완 전 기업) ──
    if args.standardize_only:
        affected = collect.needs_standardize_corps()
        logger.info(f"[collect] (재개) ④ 파싱·표준화 대상 {len(affected)}개 기업 "
                    f"(타임아웃 {args.timeout}초/기업)")
        agg = _standardize_with_timeout(affected, args.timeout) if affected else {}
        logger.success(f"[collect] 재개 완료 — std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · "
                       f"달력 {agg.get('c', 0):,} · 타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")
        return

    from collector.downloader import run_downloads
    from collector.filing_collector import sync_filings

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

    # ④ 파싱·표준화·분기·달력 (신규 기업만, 기업당 타임아웃)
    affected = collect.needs_standardize_corps(only=corps)
    logger.info(f"[collect] ④ 파싱·표준화 대상 {len(affected)}개 기업 (타임아웃 {args.timeout}초/기업)")
    agg = _standardize_with_timeout(affected, args.timeout) if affected else {}

    logger.success(f"[collect] 완료 — 신규 {len(corps)}개 기업 · fact {agg.get('e_facts', 0):,} · "
                   f"std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · 달력 {agg.get('c', 0):,} · "
                   f"타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")


if __name__ == "__main__":
    main()
