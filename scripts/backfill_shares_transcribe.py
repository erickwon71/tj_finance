"""발행주식수 계층2 전량 백필 — 2015+ 정기보고서 → `report_shares_outstanding`.

`fin2/extract/shares_transcribe.py::sync_shares_transcribe`(데일리 증분과 동일 함수)를
전체 기업 리스트에 대해 배치 호출한다. **한 번만 실행하면 끝**(계층2 적재이므로 v2 처럼
"매 rebuild 마다 재실행" 패턴이 아님) — 이후 신규 filing 은
`scripts/collect_new.py::_sync_shares_transcribe`가 데일리로 따라간다.

재개: `sync_shares_transcribe`가 corp 단위로 이미 적재된 rcept 를 자동 스킵하므로(loaded
체크, `report_shares_outstanding` 존재 유무) 이 스크립트를 그냥 다시 실행하면 재개된다
(별도 progress 테이블 불필요 — todo 문서 2C-1 `--skip-existing` 요구사항은 이 자연 재개로 충족).
단, 섹션이 없어 **결측으로 끝난 filing**(shares_out 못 찾음)은 매번 재시도 대상에 남는다
(R0 — 원문에 없으면 없는 것이므로 "실패 기록"을 별도로 안 둠). 재시도 비용은 낮음(파일당
~40ms, 실측 2026-08-09).

사용:
    python scripts/backfill_shares_transcribe.py --status       # 진행 현황만
    python scripts/backfill_shares_transcribe.py --limit 20      # 소량 시험(기업 수)
    python scripts/backfill_shares_transcribe.py                 # 전량 실행
    python scripts/backfill_shares_transcribe.py --shard 0/4     # 4분할 중 0번(병렬 실행용)
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
from fin2.extract.shares_transcribe import FY_MIN, sync_shares_transcribe

BATCH = 20  # corp 수 단위로 sync_shares_transcribe 호출(호출 안에서 자체 commit)


def _all_corps(session, year_min: int) -> list[str]:
    rows = session.execute(text("""
        SELECT DISTINCT f.corp_code
        FROM filings f JOIN download_tasks dt USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
          AND f.fiscal_year >= :ym
        ORDER BY 1
    """), {"ym": year_min}).fetchall()
    return [r[0] for r in rows]


def _status(session) -> None:
    total_filings = session.execute(text("""
        SELECT COUNT(*) FROM download_tasks dt JOIN filings f USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
          AND f.fiscal_year >= :ym
    """), {"ym": FY_MIN}).scalar()
    loaded_rows = session.execute(text(
        "SELECT COUNT(*) FROM report_shares_outstanding")).scalar()
    loaded_corps = session.execute(text(
        "SELECT COUNT(DISTINCT corp_code) FROM report_shares_outstanding")).scalar()
    total_corps = session.execute(text("""
        SELECT COUNT(DISTINCT f.corp_code)
        FROM filings f JOIN download_tasks dt USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND f.fiscal_year >= :ym
    """), {"ym": FY_MIN}).scalar()
    logger.info(f"[shares-backfill] 적재행 {loaded_rows:,} · 적재기업 {loaded_corps:,}/"
                f"{total_corps:,} · 대상필링 {total_filings:,}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처리할 기업 수 상한(시험용)")
    ap.add_argument("--shard", type=str, default=None, help="a/n — 기업 리스트 n분할 중 a번")
    ap.add_argument("--status", action="store_true", help="진행 현황만 출력하고 종료")
    ap.add_argument("--recheck", action="store_true", help="이미 적재된 rcept 도 재처리")
    args = ap.parse_args()

    with get_session() as session:
        if args.status:
            _status(session)
            return
        corps = _all_corps(session, FY_MIN)

    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        corps = [c for i, c in enumerate(corps) if i % n == a]
    if args.limit:
        corps = corps[: args.limit]

    logger.info(f"[shares-backfill] 대상 기업 {len(corps):,} — 배치 {BATCH}개씩 "
                f"{'재처리(recheck)' if args.recheck else '증분(loaded 스킵)'}")

    t0 = time.time()
    tot = {"corps": 0, "filings": 0, "rows": 0, "errors": 0}
    for i in range(0, len(corps), BATCH):
        chunk = corps[i:i + BATCH]
        res = sync_shares_transcribe(chunk, recheck=args.recheck)
        for k in tot:
            tot[k] += res[k]
        done = min(i + BATCH, len(corps))
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(corps) - done) / rate if rate > 0 else 0
        logger.info(f"[shares-backfill] {done:,}/{len(corps):,}기업 — "
                    f"필링 {tot['filings']:,} · 적재 {tot['rows']:,} · 오류 {tot['errors']} · "
                    f"{elapsed:.0f}s경과 · ETA {eta / 60:.1f}분")

    logger.success(f"[shares-backfill] 완료 — 기업 {tot['corps']:,} · 필링 {tot['filings']:,} · "
                   f"적재 {tot['rows']:,}({tot['rows'] / max(tot['filings'],1)*100:.1f}%) · "
                   f"오류 {tot['errors']} · {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
