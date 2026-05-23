"""
수집 현황 리포트 및 상태 조회
"""
from datetime import datetime, date, timedelta

from loguru import logger
from sqlalchemy import func, select, text

from collector.config import MAX_DOWNLOAD_ATTEMPTS
from collector.db import get_session
from collector.models import Corporation, Filing, DownloadTask, CollectionRun
from collector.rate_limiter import get_limiter


def print_status() -> None:
    """현재 수집 현황 요약 출력"""
    with get_session() as session:
        # 활성 기업만 집계
        total_corps = session.scalar(
            select(func.count(Corporation.corp_code)).where(Corporation.is_active == True)
        )
        inactive_corps = session.scalar(
            select(func.count(Corporation.corp_code)).where(Corporation.is_active == False)
        )
        market_counts = session.execute(
            select(Corporation.market, func.count())
            .where(Corporation.is_active == True)
            .group_by(Corporation.market)
        ).all()

        # filing_sync 진행 현황
        synced_corps = session.scalar(
            select(func.count(Corporation.corp_code))
            .where(Corporation.is_active == True, Corporation.last_filing_sync != None)
        )

        total_filings = session.scalar(select(func.count(Filing.rcept_no)))
        final_filings = session.scalar(
            select(func.count(Filing.rcept_no)).where(Filing.is_final == True)
        )

        dl_stats = session.execute(
            select(DownloadTask.status, func.count())
            .group_by(DownloadTask.status)
        ).all()
        dl_dict = dict(dl_stats)

        recent_runs = session.scalars(
            select(CollectionRun)
            .order_by(CollectionRun.started_at.desc())
            .limit(5)
        ).all()

    print("\n" + "=" * 60)
    print("  DART PDF 수집 시스템 현황")
    print("=" * 60)

    print(f"\n[기업 목록]  활성: {total_corps:,}개 / 비활성(상장폐지·제외): {inactive_corps:,}개")
    for market, cnt in sorted(market_counts, key=lambda x: x[1], reverse=True):
        print(f"  {market or 'UNKNOWN':8s}: {cnt:,}개")

    print(f"\n[공시 목록 수집]")
    pct = synced_corps / total_corps * 100 if total_corps else 0
    print(f"  filing_sync 완료: {synced_corps:,} / {total_corps:,}개 ({pct:.1f}%)")
    print(f"  전체 공시 수집: {total_filings:,}건  |  최종본: {final_filings:,}건")

    print(f"\n[다운로드 현황]")
    total_dl = sum(dl_dict.values())
    for status in ["completed", "pending", "failed", "downloading", "skipped"]:
        cnt = dl_dict.get(status, 0)
        pct = (cnt / total_dl * 100) if total_dl else 0
        print(f"  {status:12s}: {cnt:>7,}건 ({pct:5.1f}%)")

    print(f"\n[API 호출 현황]")
    limiter = get_limiter()
    print(f"  오늘 사용: {limiter.calls_today:,} / {limiter.daily_limit:,}콜")
    print(f"  잔여:      {limiter.remaining_today:,}콜")

    print(f"\n[최근 실행 이력]")
    for r in recent_runs:
        elapsed = ""
        if r.ended_at and r.started_at:
            elapsed = f" ({(r.ended_at - r.started_at).seconds}초)"
        print(
            f"  {r.started_at:%m/%d %H:%M} {r.run_type:15s} "
            f"완료 {r.completed:,} / 실패 {r.failed:,} / API {r.api_calls:,}콜{elapsed}"
        )

    print("=" * 60 + "\n")


def print_failed_downloads(limit: int = 20) -> None:
    """실패한 다운로드 목록 출력"""
    with get_session() as session:
        tasks = session.scalars(
            select(DownloadTask)
            .where(DownloadTask.status == "failed")
            .order_by(DownloadTask.last_attempt_at.desc())
            .limit(limit)
        ).all()

    print(f"\n[실패한 다운로드 (최근 {limit}건)]")
    for t in tasks:
        print(
            f"  {t.rcept_no}  시도:{t.attempts}회  "
            f"{(t.last_attempt_at or datetime.min):%m/%d %H:%M}  "
            f"{(t.last_error or '')[:80]}"
        )


def cleanup_inactive_tasks() -> int:
    """
    is_active=False 기업의 pending/failed 다운로드 작업을 skipped으로 정리.
    sync-corps로 기업 목록이 바뀐 후 실행.
    반환: 정리된 건 수
    """
    from sqlalchemy import text

    with get_session() as session:
        result = session.execute(text("""
            UPDATE download_tasks
            SET status = 'skipped'
            WHERE status IN ('pending', 'failed')
              AND rcept_no IN (
                  SELECT f.rcept_no
                  FROM filings f
                  JOIN corporations c ON f.corp_code = c.corp_code
                  WHERE c.is_active = FALSE
              )
        """))
        count = result.rowcount

    logger.info(f"비활성 기업 다운로드 작업 {count:,}건 → skipped 처리")
    return count


def reset_failed_downloads(max_attempts: int = MAX_DOWNLOAD_ATTEMPTS) -> int:
    """
    실패 건 중 시도 횟수가 max_attempts 미만인 것을 pending으로 리셋.
    기본값은 config.MAX_DOWNLOAD_ATTEMPTS (현재 3회).
    반환: 리셋 건 수
    """
    from sqlalchemy import update

    with get_session() as session:
        result = session.execute(
            update(DownloadTask)
            .where(
                DownloadTask.status == "failed",
                DownloadTask.attempts < max_attempts,
            )
            .values(status="pending")
        )
        count = result.rowcount
    logger.info(f"{count}건 다운로드 작업을 pending으로 리셋했습니다.")
    return count
