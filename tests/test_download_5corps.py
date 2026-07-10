#!/usr/bin/env python3
"""
5개 기업 다운로드 테스트 스크립트

대상: 삼성전자, 삼성바이오로직스, 신영증권, 에스원, 제주은행
실행: python test_download_5corps.py
"""
import sys
from pathlib import Path
from datetime import datetime

from loguru import logger

# ── 로거 설정 ────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    LOG_DIR / "test_5corps_{time:YYYYMMDD_HHmmss}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    level="DEBUG",
    encoding="utf-8",
)

TARGET_NAMES = ["삼성전자", "삼성바이오로직스", "신영증권", "에스원", "제주은행"]


def step1_find_corps() -> list[str]:
    """DB에서 대상 기업 corp_code 조회"""
    from sqlalchemy import text
    from collector.db import get_session

    logger.info("=" * 60)
    logger.info("STEP 1 — 대상 기업 조회")
    logger.info("=" * 60)

    corp_codes = []
    with get_session() as session:
        for name in TARGET_NAMES:
            row = session.execute(
                text("""
                    SELECT corp_code, corp_name, stock_code, market, last_filing_sync
                    FROM corporations
                    WHERE corp_name = :n
                """),
                {"n": name},
            ).fetchone()

            if row:
                synced = "수집완료" if row[4] else "미수집"
                logger.info(
                    f"  ✓ {row[1]:15s}  corp={row[0]}  stock={row[2]}  "
                    f"{row[3]:8s}  filing_sync={synced}"
                )
                corp_codes.append(row[0])
            else:
                logger.warning(f"  ✗ '{name}' — DB에서 찾지 못했습니다.")

    logger.info(f"\n  조회 완료: {len(corp_codes)}/{len(TARGET_NAMES)}개 기업 확인")
    return corp_codes


def step2_check_filings(corp_codes: list[str]) -> None:
    """각 기업의 공시 수집 현황 확인"""
    from sqlalchemy import text
    from collector.db import get_session

    logger.info("\n" + "=" * 60)
    logger.info("STEP 2 — 공시 목록 현황 확인")
    logger.info("=" * 60)

    with get_session() as session:
        for code in corp_codes:
            rows = session.execute(
                text("""
                    SELECT
                        c.corp_name,
                        f.report_type,
                        COUNT(*)            AS total,
                        SUM(CASE WHEN f.is_final THEN 1 ELSE 0 END) AS finals,
                        MIN(f.fiscal_year)  AS min_yr,
                        MAX(f.fiscal_year)  AS max_yr
                    FROM filings f
                    JOIN corporations c ON f.corp_code = c.corp_code
                    WHERE f.corp_code = :code
                    GROUP BY c.corp_name, f.report_type
                    ORDER BY f.report_type
                """),
                {"code": code},
            ).fetchall()

            if rows:
                corp_name = rows[0][0]
                logger.info(f"\n  [{corp_name}]")
                for r in rows:
                    logger.info(
                        f"    {r[1]:8s}: 전체 {r[2]:3d}건 / 최종본 {r[3]:3d}건  "
                        f"({r[4]}~{r[5]})"
                    )
            else:
                logger.warning(f"  [{code}] 공시 데이터 없음")

        # 다운로드 작업 현황
        logger.info("\n  [다운로드 작업 현황]")
        for code in corp_codes:
            rows = session.execute(
                text("""
                    SELECT c.corp_name, dt.status, COUNT(*)
                    FROM download_tasks dt
                    JOIN filings f ON dt.rcept_no = f.rcept_no
                    JOIN corporations c ON f.corp_code = c.corp_code
                    WHERE f.corp_code = :code
                    GROUP BY c.corp_name, dt.status
                    ORDER BY dt.status
                """),
                {"code": code},
            ).fetchall()

            if rows:
                corp_name = rows[0][0]
                status_str = "  ".join(f"{r[1]}:{r[2]}" for r in rows)
                logger.info(f"    {corp_name:15s}: {status_str}")
            else:
                logger.warning(f"    {code}: 다운로드 작업 없음")


def step3_run_download(corp_codes: list[str]) -> dict:
    """기업 단위로 순서대로 다운로드 실행"""
    from sqlalchemy import text
    from collector.downloader import run_downloads
    from collector.db import get_session

    logger.info("\n" + "=" * 60)
    logger.info("STEP 3 — PDF 다운로드 시작 (기업별 순서)")
    logger.info("=" * 60)
    logger.info(f"  시작 시각: {datetime.now():%Y-%m-%d %H:%M:%S}")

    total = {"total_queued": 0, "completed": 0, "failed": 0, "skipped": 0}

    for corp_code in corp_codes:
        # 기업명 조회
        with get_session() as session:
            row = session.execute(
                text("SELECT corp_name FROM corporations WHERE corp_code = :c"),
                {"c": corp_code},
            ).fetchone()
        corp_name = row[0] if row else corp_code

        logger.info(f"\n  ── {corp_name} ({corp_code}) ──")
        result = run_downloads(only_corp_codes=[corp_code])

        for key in total:
            total[key] += result.get(key, 0)

    return total


def step4_verify(corp_codes: list[str]) -> None:
    """다운로드 결과 검증 — 파일 실제 존재 여부 확인"""
    from sqlalchemy import text
    from collector.db import get_session
    from collector.config import RAW_REPORT_DIR

    logger.info("\n" + "=" * 60)
    logger.info("STEP 4 — 결과 검증")
    logger.info("=" * 60)

    with get_session() as session:
        for code in corp_codes:
            rows = session.execute(
                text("""
                    SELECT
                        c.corp_name,
                        dt.status,
                        dt.file_path,
                        dt.file_type,
                        dt.file_size,
                        dt.attempts,
                        dt.last_error,
                        f.fiscal_year,
                        f.report_type
                    FROM download_tasks dt
                    JOIN filings f ON dt.rcept_no = f.rcept_no
                    JOIN corporations c ON f.corp_code = c.corp_code
                    WHERE f.corp_code = :code
                      AND f.is_final = TRUE
                    ORDER BY f.fiscal_year DESC, f.report_type
                """),
                {"code": code},
            ).fetchall()

            if not rows:
                continue

            corp_name = rows[0][0]
            completed = [r for r in rows if r[1] == "completed"]
            failed    = [r for r in rows if r[1] == "failed"]
            pending   = [r for r in rows if r[1] == "pending"]

            logger.info(f"\n  [{corp_name}]  완료:{len(completed)}  실패:{len(failed)}  대기:{len(pending)}")

            # 완료 파일 존재 확인
            for r in completed:
                if r[2]:
                    p = Path(r[2])
                    size_mb = (r[4] or 0) / 1024 / 1024
                    exists = "✓" if p.exists() else "✗ 파일없음!"
                    logger.info(
                        f"    {exists} {r[7]}{r[8]:8s}  "
                        f"{p.name}  ({size_mb:.1f} MB)"
                    )

            # 실패 원인 출력
            for r in failed:
                logger.warning(
                    f"    ✗ FAIL  {r[7]}{r[8]:8s}  "
                    f"시도:{r[5]}회  {(r[6] or '')[:80]}"
                )

    # 저장 디렉토리 실제 파일 수 확인
    logger.info(f"\n  [raw_report 디렉토리 확인]")
    for code in corp_codes:
        from sqlalchemy import text
        with get_session() as session:
            name_row = session.execute(
                text("SELECT corp_name FROM corporations WHERE corp_code = :c"),
                {"c": code},
            ).fetchone()
        if not name_row:
            continue
        corp_name = name_row[0]

        # 저장된 파일 검색 (market 구분 무관)
        pattern = f"{code}_*"
        matched_dirs = list(RAW_REPORT_DIR.glob(f"*/{pattern}"))
        if matched_dirs:
            total_files = sum(1 for d in matched_dirs for _ in d.rglob("*") if _.is_file())
            total_size  = sum(f.stat().st_size for d in matched_dirs for f in d.rglob("*") if f.is_file())
            logger.info(
                f"    {corp_name:15s}: {total_files}개 파일  "
                f"({total_size / 1024 / 1024:.1f} MB)  → {matched_dirs[0]}"
            )
        else:
            logger.warning(f"    {corp_name:15s}: 저장된 파일 없음")


def main():
    logger.info("=" * 60)
    logger.info("  5개 기업 다운로드 테스트")
    logger.info(f"  실행 시각: {datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info("=" * 60)

    # STEP 1: 기업 조회
    corp_codes = step1_find_corps()
    if not corp_codes:
        logger.error("대상 기업을 찾지 못했습니다. DB를 확인하세요.")
        sys.exit(1)

    # STEP 2: 공시 현황 확인
    step2_check_filings(corp_codes)

    # STEP 3: 다운로드 실행
    result = step3_run_download(corp_codes)

    # STEP 4: 결과 검증
    step4_verify(corp_codes)

    # 최종 요약
    logger.info("\n" + "=" * 60)
    logger.info("  최종 요약")
    logger.info("=" * 60)
    logger.info(f"  전체 대기: {result['total_queued']:,}건")
    logger.info(f"  성공:      {result['completed']:,}건")
    logger.info(f"  실패:      {result['failed']:,}건")
    logger.info(f"  종료 시각: {datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
