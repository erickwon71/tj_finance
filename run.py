#!/usr/bin/env python3
"""
DART PDF 수집 시스템 — CLI 진입점

사용법:
  python run.py init          # DB 초기화 (최초 1회)
  python run.py sync-corps    # 기업 목록 동기화
  python run.py sync-filings  # 공시 목록 동기화 (전체 기업)
  python run.py sync-filings --corp 00126380  # 특정 기업만
  python run.py download      # PDF 다운로드
  python run.py download --limit 100           # 최대 100건만
  python run.py download --corp 00126380       # 특정 기업만
  python run.py status        # 현황 조회
  python run.py failed        # 실패 목록 조회
  python run.py reset-failed  # 실패 건 재시도 등록
  python run.py all           # sync-corps → sync-filings → download 순서 실행
  python run.py deactivate    # DB의 제외 대상 기업(선박투자/리츠 등) 비활성화
"""
import argparse
import sys
from pathlib import Path

from loguru import logger

# ── 로거 설정 ─────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()  # 기본 핸들러 제거
logger.add(
    sys.stderr,
    format="<green>{time:MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    LOG_DIR / "dart_{time:YYYYMMDD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    level="DEBUG",
    rotation="00:00",     # 자정에 로그 파일 교체
    retention="30 days",  # 30일치 보관
    encoding="utf-8",
)


def cmd_init(args):
    """DB 초기화"""
    from collector.db import init_db
    init_db()
    logger.success("DB 초기화 완료")


def cmd_sync_corps(args):
    """기업 목록 동기화"""
    from collector.corp_collector import sync_corporations
    result = sync_corporations()
    logger.success(f"완료: {result}")


def cmd_deactivate(args):
    """DB의 제외 대상 기업 비활성화 (선박투자/리츠 등)"""
    from collector.corp_collector import deactivate_excluded_corps
    result = deactivate_excluded_corps()
    logger.success(f"완료: {result}")


def cmd_sync_filings(args):
    """공시 목록 동기화"""
    from collector.filing_collector import sync_filings
    corp_codes = [args.corp] if args.corp else None
    result = sync_filings(corp_codes=corp_codes, force=getattr(args, "force", False))
    logger.success(f"완료: {result}")


def cmd_download(args):
    """PDF 다운로드"""
    from collector.downloader import run_downloads
    corp_codes = [args.corp] if args.corp else None
    result = run_downloads(
        limit=args.limit,
        only_corp_codes=corp_codes,
    )
    logger.success(f"완료: {result}")


def cmd_status(args):
    """현황 조회"""
    from collector.runner import print_status
    print_status()


def cmd_failed(args):
    """실패 목록 조회"""
    from collector.runner import print_failed_downloads
    print_failed_downloads()


def cmd_reset_failed(args):
    """실패 건 재시도 등록"""
    from collector.runner import reset_failed_downloads
    reset_failed_downloads()


def cmd_cleanup(args):
    """비활성 기업의 pending 다운로드 작업 정리"""
    from collector.runner import cleanup_inactive_tasks
    cleanup_inactive_tasks()


def cmd_all(args):
    """전체 파이프라인 순서 실행"""
    logger.info("=== 전체 파이프라인 시작 ===")
    cmd_sync_corps(args)
    cmd_sync_filings(args)
    cmd_download(args)
    logger.success("=== 전체 파이프라인 완료 ===")


# ── CLI 파서 ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="DART PDF 수집 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "command",
        choices=[
            "init", "sync-corps", "sync-filings",
            "download", "status", "failed", "reset-failed", "all",
            "deactivate", "cleanup",
        ],
        help="실행할 명령",
    )
    parser.add_argument(
        "--corp",
        metavar="CORP_CODE",
        help="특정 기업 DART 고유코드 (8자리). sync-filings, download에서 사용.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="download: 최대 처리 건 수",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="sync-filings: last_filing_sync 무시하고 전체 재수집",
    )

    args = parser.parse_args()

    dispatch = {
        "init":          cmd_init,
        "sync-corps":    cmd_sync_corps,
        "sync-filings":  cmd_sync_filings,
        "download":      cmd_download,
        "status":        cmd_status,
        "failed":        cmd_failed,
        "reset-failed":  cmd_reset_failed,
        "all":           cmd_all,
        "deactivate":    cmd_deactivate,
        "cleanup":       cmd_cleanup,
    }

    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        logger.warning("사용자 중단 (Ctrl+C). 진행 상태는 DB에 저장되어 있습니다.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
