#!/usr/bin/env python3
"""
DART PDF 수집 시스템 — CLI 진입점

사용법:
  python run.py init          # DB 초기화 (최초 1회)
  python run.py sync-corps    # 기업 목록 동기화
  python run.py sync-filings  # 공시 목록 동기화 (전체 기업)
  python run.py sync-filings --corp 00126380        # 특정 기업만
  python run.py download                            # PDF 다운로드 (전체)
  python run.py download --limit 100                # 최대 100건만
  python run.py download --corp 00126380            # 특정 기업 1개만
  python run.py download --corps 0:10               # 기업 목록 0~9번째 (10개)
  python run.py download --corps 10:20              # 기업 목록 10~19번째 (10개)
  python run.py list-corps                          # 번호 붙은 기업 목록 출력
  python run.py list-corps --page 2                 # 101~200번 출력
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


def _get_active_corp_codes() -> list[str]:
    """
    다운로드 대상이 있는 활성 기업 목록을 corp_code 순으로 반환.
    (pending/failed 건이 1개 이상 있는 기업만 포함)
    """
    from sqlalchemy import text
    from collector.db import get_session

    with get_session() as session:
        rows = session.execute(text("""
            SELECT DISTINCT c.corp_code
            FROM corporations c
            JOIN filings f ON f.corp_code = c.corp_code
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE c.is_active = TRUE
              AND f.is_final = TRUE
              AND dt.status IN ('pending', 'failed')
            ORDER BY c.corp_code
        """)).fetchall()
    return [r[0] for r in rows]


def _parse_corps_slice(corps_arg: str, all_codes: list[str]) -> list[str]:
    """
    '--corps 0:10' 형식을 파싱해 corp_code 리스트로 변환.
    단일 인덱스 '5' 도 지원 (해당 기업 1개).
    """
    if ":" in corps_arg:
        parts = corps_arg.split(":", 1)
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else len(all_codes)
    else:
        idx   = int(corps_arg)
        start, end = idx, idx + 1

    sliced = all_codes[start:end]
    if not sliced:
        raise ValueError(
            f"--corps {corps_arg} 범위가 전체 기업 수({len(all_codes)}개)를 벗어났습니다."
        )
    return sliced


def cmd_download(args):
    """PDF 다운로드"""
    from collector.downloader import run_downloads

    corp_codes: list[str] | None = None

    if getattr(args, "corp", None):
        corp_codes = [args.corp]
    elif getattr(args, "corps", None):
        all_codes  = _get_active_corp_codes()
        corp_codes = _parse_corps_slice(args.corps, all_codes)
        logger.info(
            f"--corps {args.corps} → {len(corp_codes)}개 기업 "
            f"(전체 {len(all_codes)}개 중 인덱스 선택)"
        )
        # 선택된 기업 목록 미리 출력
        for i, code in enumerate(corp_codes):
            from collector.db import get_session
            from sqlalchemy import text
            with get_session() as session:
                row = session.execute(
                    text("SELECT corp_name FROM corporations WHERE corp_code = :c"),
                    {"c": code},
                ).fetchone()
            name = row[0] if row else "?"
            start_idx = (
                int(args.corps.split(":")[0]) if ":" in args.corps else int(args.corps)
            )
            logger.info(f"  [{start_idx + i:>4}] {code}  {name}")

    result = run_downloads(
        limit=getattr(args, "limit", None),
        only_corp_codes=corp_codes,
    )
    logger.success(f"완료: {result}")


def cmd_list_corps(args):
    """번호 붙은 활성 기업 목록 출력 (--corps 인덱스 확인용)"""
    from sqlalchemy import text
    from collector.db import get_session

    page     = getattr(args, "page", 1) or 1
    per_page = 100
    offset   = (page - 1) * per_page

    with get_session() as session:
        rows = session.execute(text("""
            SELECT c.corp_code, c.corp_name, c.market,
                   COUNT(dt.rcept_no) AS pending_cnt
            FROM corporations c
            JOIN filings f ON f.corp_code = c.corp_code
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE c.is_active = TRUE
              AND f.is_final = TRUE
              AND dt.status IN ('pending', 'failed')
            GROUP BY c.corp_code, c.corp_name, c.market
            ORDER BY c.corp_code
        """)).fetchall()

    total = len(rows)
    page_rows = rows[offset : offset + per_page]

    logger.info(f"활성 기업 (다운로드 대기 있는 기업) — 총 {total}개  [페이지 {page}]")
    logger.info(f"{'idx':>5}  {'corp_code':10}  {'market':8}  {'대기건수':>6}  corp_name")
    logger.info("-" * 65)
    for i, r in enumerate(page_rows):
        global_idx = offset + i
        logger.info(f"{global_idx:>5}  {r[0]:10}  {r[2] or '':8}  {r[3]:>6}건  {r[1]}")

    if total > offset + per_page:
        next_page = page + 1
        logger.info(f"\n  다음 페이지: python run.py list-corps --page {next_page}")


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
            "download", "list-corps",
            "status", "failed", "reset-failed", "all",
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
        "--corps",
        metavar="START:END",
        help=(
            "download: list-corps 인덱스 범위로 기업 선택. "
            "예) --corps 0:10 (0~9번째), --corps 20:30, --corps 5 (5번째 1개). "
            "--corp 과 동시 사용 불가."
        ),
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
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        metavar="N",
        help="list-corps: 페이지 번호 (100개씩, 기본값 1)",
    )

    args = parser.parse_args()

    # --corp / --corps 동시 사용 방지
    if getattr(args, "corp", None) and getattr(args, "corps", None):
        parser.error("--corp 과 --corps 는 동시에 사용할 수 없습니다.")

    dispatch = {
        "init":          cmd_init,
        "sync-corps":    cmd_sync_corps,
        "sync-filings":  cmd_sync_filings,
        "download":      cmd_download,
        "list-corps":    cmd_list_corps,
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
