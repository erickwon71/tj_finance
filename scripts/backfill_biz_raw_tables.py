"""Phase 5-2 백필 (biz_content_layer2_migration_2026-08-09) — biz_section_tables 전량 재추출.

annual 보고서(다운로드 완료 XML) 전체를 `extract_biz_raw_tables`로 다시 뽑아
`store_biz_raw_tables`(rcept 단위 delete-then-insert)로 재적재한다. Phase3 검증 중 발견한
버그 2건(도메인 오분류 6,148행, narrative 4000자 절단 3,128행)이 이미 수정된 현재 코드로
돌기 때문에, order_backlog(신규 도메인)뿐 아니라 기존 528,564행(production/sales/catalog)의
잔여 영향도 이 한 번의 실행으로 함께 해소된다 — order_backlog 전용 백필이 아니라 사실상
전체 재추출(TODO 5-2 확정 사항).

모집단·소요시간 실측 = Phase 0(`scripts/probe_order_backlog_reparse_cost.py`,
53,952건 · 평균 103.8ms/필링 · 추정 93.4분, 단일 프로세스).

재개: 이 스크립트는 멱등(rcept 단위 delete-then-insert)이라 중단 후 다시 돌려도 안전하다.
전량 재추출이 목적이므로(과거 코드로 쓰인 행을 구분할 표지가 없음) "완료됨" 표지는 DB에 없지만,
모집단이 rcept_no 오름차순으로 결정적이라 진행 위치를 체크포인트 파일(`--checkpoint-file`)에
기록해 **어디까지 커밋됐는지**로 재개한다(2026-08-09 실행 중 60분 지점에서 원인불명 kill 1회
발생 — 환경 쪽 장시간 프로세스 제약으로 추정, 재발 대비 추가). `--restart`로 체크포인트 무시하고
처음부터. 필링 단위 SAVEPOINT로 개별 실패를 격리하고, N필링마다 커밋해 중단 시 유실 범위를
제한한다.

사용:
    python scripts/backfill_biz_raw_tables.py --status        # 진행 현황만
    python scripts/backfill_biz_raw_tables.py --limit 50       # 소량 시험(필링 수)
    python scripts/backfill_biz_raw_tables.py                  # 전량 실행(체크포인트 있으면 재개)
    python scripts/backfill_biz_raw_tables.py --restart         # 체크포인트 무시, 처음부터
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
from fin2.layer2.biz_raw_tables import extract_biz_raw_tables, store_biz_raw_tables

_DEFAULT_CHECKPOINT = ("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                       "d9e8f238-f638-47d1-a040-51346751edb2/scratchpad/"
                       "biz_raw_backfill_checkpoint.txt")

_COUNT_SQL = """
    SELECT COUNT(*)
    FROM filings f
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE f.report_type = 'annual'
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
"""

_POPULATION_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, dt.file_path
    FROM filings f
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE f.report_type = 'annual'
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
    ORDER BY f.rcept_no
"""


def _domain_counts(session) -> dict:
    rows = session.execute(text(
        "SELECT domain, COUNT(*) FROM biz_section_tables GROUP BY domain ORDER BY domain")).fetchall()
    return {r[0]: r[1] for r in rows}


def _status(session) -> None:
    total = session.execute(text(_COUNT_SQL)).scalar()
    counts = _domain_counts(session)
    logger.info(f"[biz-raw-backfill] 대상필링 {total:,} · 현재 biz_section_tables 도메인별: {counts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처리할 필링 수 상한(시험용)")
    ap.add_argument("--status", action="store_true", help="진행 현황만 출력하고 종료")
    ap.add_argument("--commit-every", type=int, default=50, help="N 필링마다 커밋")
    ap.add_argument("--checkpoint-file", default=_DEFAULT_CHECKPOINT,
                    help="진행 위치(마지막 커밋 rcept_no) 저장 파일")
    ap.add_argument("--restart", action="store_true", help="체크포인트 무시하고 처음부터")
    args = ap.parse_args()

    with get_session() as session:
        if args.status:
            _status(session)
            return
        rows = session.execute(text(_POPULATION_SQL)).fetchall()
        before = _domain_counts(session)

    if args.limit:
        rows = rows[: args.limit]

    ckpt_path = Path(args.checkpoint_file)
    if args.restart:
        ckpt_path.unlink(missing_ok=True)
    elif ckpt_path.exists():
        last_rcept = ckpt_path.read_text().strip()
        skip_to = next((i for i, r in enumerate(rows) if r.rcept_no > last_rcept), len(rows))
        if skip_to:
            logger.info(f"[biz-raw-backfill] 체크포인트 발견({last_rcept}) — "
                        f"{skip_to:,}건 스킵하고 재개")
            rows = rows[skip_to:]

    total = len(rows)
    logger.info(f"[biz-raw-backfill] 대상 {total:,}건 재추출 시작 (도메인별 기존: {before})")

    t0 = time.perf_counter()
    ok = 0
    missing = 0
    extract_errors = 0
    store_errors = 0
    total_rows_written = 0

    with get_session() as session:
        for i, r in enumerate(rows, 1):
            fp = Path(r.file_path)
            if not fp.exists():
                missing += 1
                continue

            try:
                extracted = extract_biz_raw_tables(fp, r.corp_code, r.fiscal_year)
            except Exception as exc:  # noqa: BLE001
                extract_errors += 1
                logger.warning(f"[biz-raw-backfill] {r.rcept_no} 추출 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue

            try:
                with session.begin_nested():  # SAVEPOINT — 이 필링만 실패해도 배치 나머지는 보존
                    n = store_biz_raw_tables(session, r.rcept_no, extracted)
                total_rows_written += n
                ok += 1
            except Exception as exc:  # noqa: BLE001
                store_errors += 1
                logger.warning(f"[biz-raw-backfill] {r.rcept_no} 저장 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue

            if i % args.commit_every == 0:
                session.commit()
                ckpt_path.write_text(r.rcept_no)
            if i % 1000 == 0 or i == total:
                elapsed = time.perf_counter() - t0
                rate = i / elapsed
                eta_min = (total - i) / rate / 60 if rate > 0 else 0
                logger.info(f"  ..{i:,}/{total:,} (성공 {ok:,} 결측 {missing:,} "
                            f"추출오류 {extract_errors:,} 저장오류 {store_errors:,} "
                            f"적재행 {total_rows_written:,} · {elapsed/60:.1f}분 경과 · "
                            f"ETA {eta_min:.1f}분)")
        session.commit()
        after = _domain_counts(session)

    if not args.limit:  # --limit 시험 실행은 "완주"가 아니므로 체크포인트 보존
        ckpt_path.unlink(missing_ok=True)  # 전체 완주 — 다음 실행은 다시 처음부터가 기본값

    elapsed = time.perf_counter() - t0
    logger.success(f"[biz-raw-backfill] 완료 — 대상 {total:,} · 성공 {ok:,} · 결측 {missing:,} · "
                    f"추출오류 {extract_errors:,} · 저장오류 {store_errors:,} · "
                    f"적재행 {total_rows_written:,} · {elapsed/60:.1f}분")
    logger.success(f"[biz-raw-backfill] 도메인별 — 이전: {before} / 이후: {after}")


if __name__ == "__main__":
    main()
