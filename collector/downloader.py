"""
보고서 파일 다운로더
Step 3: download_tasks 테이블의 pending/failed 건을 순서대로 처리

처리 흐름:
  1. DART document.xml API → ZIP 다운로드
  2. ZIP 압축 해제 → 파일 유형 분류 (xml > pdf > html > hwp > zip)
  3. raw_report/{market}/{corp_code}_{corp_name}/{report_type}/{fiscal_year}/ 에 저장
  4. download_tasks 상태 업데이트

DART 제출 형식:
  - ~2023: PDF 또는 HWP 위주
  - 2024~: iXBRL(.xml) 위주 — 분기/반기보고서는 사실상 전면 전환됨
    (XML 안에 HTML + XBRL 태그가 내장된 인라인 XBRL 형식)

파일 우선순위: xml > xbrl > pdf > html > hwp > zip
  - DART XML(dart4.xsd)은 XBRL ACODE 속성이 내장된 정형 데이터 → 파싱 정확도 최고
  - PDF는 XML이 없을 때만 사용 (구형 문서용 폴백)

재시작 안전성:
  - completed 건은 완전히 건너뜀
  - downloading 상태로 남아있는 건(이전 크래시)은 pending으로 리셋 후 재처리
"""
import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import func, select, update, or_

from collector.config import (
    RAW_REPORT_DIR, TMP_DIR,
    MAX_DOWNLOAD_ATTEMPTS, MIN_DOWNLOAD_INTERVAL,
)
from collector.dart_client import DartClient, DartApiError
from collector.rate_limiter import DailyQuotaReached


class DartApiQuotaError(DailyQuotaReached):
    """DART API 일일 사용량 소진 (서버 오류코드 020) — 즉시 종료 신호.

    클라이언트 측 호출 한도(DailyQuotaReached)와 동일한 처리 경로로 다룬다.
    """
from collector.db import get_session
from collector.models import Corporation, Filing, DownloadTask, CollectionRun


# ── 파일 확장자 우선순위 ─────────────────────────────────────────────
# xml/xbrl 최우선: DART XML(dart4.xsd)은 XBRL ACODE 속성이 내장된 정형 데이터.
#   파서가 계정과목을 ACODE로 직접 추출 → PDF 파싱 복잡도 80% 제거.
# pdf 폴백: XML이 없는 구형 문서(~2020년 이전)용.
_EXT_PRIORITY = [".xml", ".xbrl", ".pdf", ".html", ".htm", ".hwp", ".zip"]

# 여러 개일 때 가장 큰 파일(본문)을 선택할 확장자
_PICK_LARGEST_EXTS = {".pdf", ".xml", ".xbrl"}

# 재무제표가 담긴 PDF를 식별하는 파일명 키워드 (구형 DART ZIP 대응)
# 우선순위 순서대로: 재무 관련 키워드 → 가장 큰 파일(폴백)
_FINANCIAL_PDF_KEYWORDS = [
    '재무제표', '재무상태표', '손익계산서', '현금흐름표',
    'financial', '결산', '별첨재무', '첨부재무',
]


def _pick_best_pdf(candidates: list) -> "zipfile.ZipInfo":
    """
    ZIP 내 PDF 파일이 여러 개일 때 재무제표가 있을 가능성이 높은 파일 선택.

    선택 기준 (우선순위):
      1. 재무제표 키워드가 파일명에 포함된 파일 (첫 번째 매칭)
      2. 없으면 가장 큰 파일 (메인 보고서 본문일 가능성 높음)
    """
    for kw in _FINANCIAL_PDF_KEYWORDS:
        for info in candidates:
            if kw in info.filename:
                logger.debug(
                    f"  PDF 키워드 선택 [{kw}]: {info.filename} "
                    f"({info.file_size / 1024:.0f} KB)"
                )
                return info
    # 폴백: 가장 큰 파일
    return max(candidates, key=lambda i: i.file_size)


def _pick_best_file_by_size(zf: zipfile.ZipFile) -> Optional[zipfile.ZipInfo]:
    """
    ZIP 내에서 우선순위에 따라 최적 파일 선택.

    - xml / xbrl: 여러 개면 가장 큰 파일
    - pdf: 여러 개면 재무제표 키워드 우선, 없으면 가장 큰 파일
    - html / hwp / zip: 첫 번째 매칭
    ZIP에 아무것도 없으면 None 반환 → 호출부에서 'skipped' 처리.

    비고: 현재 ZIP 한 개당 파일 한 개만 저장 (DownloadTask 1:1 구조).
          재무제표가 여러 별첨 PDF에 분산된 경우 주 파일만 저장되며,
          나머지는 파싱 대상에서 제외됨 (구형 2000~2005년 보고서 일부 해당).
    """
    infos = zf.infolist()
    for ext in _EXT_PRIORITY:
        candidates = [i for i in infos if i.filename.lower().endswith(ext)]
        if candidates:
            if ext == ".pdf":
                if len(candidates) > 1:
                    logger.debug(
                        f"  ZIP 내 PDF {len(candidates)}개 발견 → "
                        f"재무제표 키워드 우선 선택"
                    )
                return _pick_best_pdf(candidates)
            if ext in _PICK_LARGEST_EXTS:
                return max(candidates, key=lambda i: i.file_size)
            return candidates[0]
    return None


def _parse_dart_xml_error(raw: bytes) -> tuple[str, str]:
    """
    DART XML 에러 응답 파싱.
    반환: (status_code, message)
    ZIP이 아닌 비XML 응답은 ValueError raise.
    """
    import xml.etree.ElementTree as ET

    if raw[:1] != b"<":
        raise ValueError(f"ZIP이 아닌 응답 수신 (첫 4바이트: {raw[:4].hex()})")

    try:
        root    = ET.fromstring(raw.decode("utf-8", errors="replace"))
        status  = (root.findtext("status")  or "").strip()
        message = (root.findtext("message") or "알 수 없는 오류").strip()
        return status, message
    except ET.ParseError:
        raise ValueError(f"비ZIP XML 파싱 실패 (첫 50바이트: {raw[:50]})")


def _mark_skipped(rcept_no: str, reason: str) -> None:
    """download_tasks 행을 skipped로 업데이트"""
    with get_session() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.rcept_no == rcept_no)
            .values(status="skipped", last_error=reason)
        )


def _build_file_path(
    corp: Corporation,
    filing: Filing,
) -> Path:
    """
    저장 경로 생성.
    raw_report/{market}/{corp_code}_{safe_name}/{report_type}/{fiscal_year}/{rcept_no}.{ext}
    → ext는 저장 시점에 결정되므로 여기서는 디렉토리까지만 반환.
    """
    market = corp.market or "UNKNOWN"
    folder_name = f"{corp.corp_code}_{corp.safe_name()}"
    dest_dir = (
        RAW_REPORT_DIR
        / market
        / folder_name
        / filing.report_type
        / str(filing.fiscal_year or "unknown")
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir


def _try_xbrl_instance_fallback(
    scraper: "LegacyDartScraper",
    task: DownloadTask,
    filing: Filing,
    corp: Corporation,
) -> Optional[bool]:
    """
    OpenDART 014 오류 시, 웹 뷰어(PDF/HTML) 폴백보다 **먼저** 표준 XBRL 원문(ifrs.do) 시도.
    docs/plans/xbrl_instance_parser_2026-08-05.md — 정형 데이터라 PDF 텍스트 파싱보다 우선.

    실패(파라미터 추출 실패/XBRL 부재)해도 예외를 던지지 않고 None만 반환 —
    호출부가 그대로 기존 `_try_legacy_fallback()`으로 이어지게 한다(회귀 없음).
    반환: True=completed, None=여기서는 못 받음(호출부가 다음 폴백 시도)
    """
    logger.info(f"  ↷ API 014 → XBRL 원문(ifrs.do) 시도...")
    try:
        zip_bytes, dcm_no = scraper.fetch_xbrl_zip(task.rcept_no)
    except Exception as e:
        logger.debug(f"  XBRL fetch 오류: {e}")
        return None

    if not zip_bytes:
        return None

    dest_dir  = _build_file_path(corp, filing)
    dest_path = dest_dir / f"{task.rcept_no}.zip"
    tmp_path  = TMP_DIR / f"{task.rcept_no}.zip"

    tmp_path.write_bytes(zip_bytes)
    shutil.move(str(tmp_path), dest_path)

    file_size = dest_path.stat().st_size
    logger.success(
        f"  ✓ 저장 완료 [XBRL 원문]: {dest_path.relative_to(RAW_REPORT_DIR)} "
        f"({file_size / 1024:.0f} KB)"
    )
    _mark_completed(
        task.rcept_no, dest_path, "xbrl_zip", file_size,
        parser_track="XBRL_INSTANCE", dcm_no=dcm_no,
    )
    return True


def _try_legacy_fallback(
    scraper: "LegacyDartScraper",
    task: DownloadTask,
    filing: Filing,
    corp: Corporation,
    api_err_msg: str,
) -> Optional[bool]:
    """
    OpenDART 014 오류 시 DART 웹에서 직접 수집 시도.
    순서: PDF 우선 → HTML 뷰어 폴백
    반환: True=completed, None=skipped
    """
    logger.info(f"  ↷ API 014 → 레거시 폴백 시도 (PDF 우선)...")
    content, fmt = scraper.fetch(task.rcept_no)

    if content:
        ext       = f".{fmt}"
        dest_dir  = _build_file_path(corp, filing)
        dest_path = dest_dir / f"{task.rcept_no}{ext}"
        tmp_path  = TMP_DIR / f"{task.rcept_no}{ext}"

        tmp_path.write_bytes(content)
        shutil.move(str(tmp_path), dest_path)

        file_size = dest_path.stat().st_size
        fmt_label = "legacy PDF" if fmt == "pdf" else "legacy HTML"
        logger.success(
            f"  ✓ 저장 완료 [{fmt_label}]: {dest_path.relative_to(RAW_REPORT_DIR)} "
            f"({file_size / 1024:.0f} KB)"
        )
        _mark_completed(task.rcept_no, dest_path, fmt, file_size)
        return True

    # PDF + HTML 모두 실패 → skipped
    reason = f"{api_err_msg} + 레거시 폴백 실패"
    logger.warning(f"  ↷ 레거시 폴백 실패 → skipped: {reason}")
    _mark_skipped(task.rcept_no, reason)
    return None


def _reset_stale_downloading(session) -> int:
    """
    'downloading' 상태로 멈춰있는 건(이전 크래시) → 'pending' 리셋.
    반환: 리셋 건 수
    """
    result = session.execute(
        update(DownloadTask)
        .where(DownloadTask.status == "downloading")
        .values(status="pending", last_error="이전 실행 크래시로 인한 리셋")
    )
    return result.rowcount


# ── 메인 다운로드 함수 ────────────────────────────────────────────────

def run_downloads(
    limit: Optional[int] = None,
    only_corp_codes: Optional[list[str]] = None,
) -> dict:
    """
    pending/failed(시도횟수 < MAX) download_tasks를 순서대로 처리.

    Args:
        limit:           처리할 최대 건 수 (None이면 전부)
        only_corp_codes: 지정 기업만 처리

    반환: {total_queued, completed, failed, skipped}
    """
    from collector.legacy_downloader import LegacyDartScraper

    client  = DartClient()
    scraper = LegacyDartScraper()
    run = CollectionRun(run_type="download", started_at=datetime.utcnow())
    stats = {"total_queued": 0, "completed": 0, "failed": 0, "skipped": 0}

    try:
        with get_session() as session:
            reset_count = _reset_stale_downloading(session)
            if reset_count:
                logger.warning(f"{reset_count}건의 stale 'downloading' 상태를 리셋했습니다.")

        # ── 처리 대상 쿼리 ───────────────────────────────────
        with get_session() as session:
            q = (
                select(DownloadTask)
                .join(Filing, DownloadTask.rcept_no == Filing.rcept_no)
                .join(Corporation, Filing.corp_code == Corporation.corp_code)
                .where(
                    DownloadTask.status.in_(["pending", "failed"]),
                    or_(
                        DownloadTask.attempts == None,
                        DownloadTask.attempts < MAX_DOWNLOAD_ATTEMPTS,
                    ),
                )
                .order_by(
                    Filing.corp_code.asc(),
                    Filing.fiscal_year.desc(),
                    DownloadTask.rcept_no.asc(),
                )
            )
            if only_corp_codes:
                q = q.where(Filing.corp_code.in_(only_corp_codes))
            if limit:
                q = q.limit(limit)

            tasks = session.scalars(q).all()

        stats["total_queued"] = len(tasks)
        logger.info(f"다운로드 대기 건수: {len(tasks):,}건")

        for idx, task in enumerate(tasks, 1):
            # 매 건마다 최신 DB 상태로 filing/corp 정보 로드
            with get_session() as session:
                filing = session.get(Filing, task.rcept_no)
                corp   = session.get(Corporation, filing.corp_code)

            logger.info(
                f"[{idx:>5}/{len(tasks)}] {corp.corp_name} "
                f"{filing.fiscal_year}{filing.fiscal_period} "
                f"{filing.report_type} ({task.rcept_no})"
            )

            try:
                result = _download_one(client, task, filing, corp, scraper)
            except DailyQuotaReached:
                logger.warning(
                    f"  → 중단 시점: 성공 {stats['completed']:,} / "
                    f"실패 {stats['failed']:,} / 스킵 {stats['skipped']:,}"
                )
                break
            if result is True:
                stats["completed"] += 1
            elif result is None:
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

        # 실행 이력
        with get_session() as session:
            run.ended_at  = datetime.utcnow()
            run.total     = stats["total_queued"]
            run.completed = stats["completed"]
            run.failed    = stats["failed"]
            run.skipped   = stats["skipped"]
            run.api_calls = stats["completed"] + stats["failed"] + stats["skipped"]
            session.add(run)

        logger.success(
            f"다운로드 완료 — "
            f"성공 {stats['completed']:,} / 실패 {stats['failed']:,} / "
            f"스킵 {stats['skipped']:,} / 전체 {stats['total_queued']:,}건"
        )
        return stats

    finally:
        client.close()
        scraper.close()


def _download_one(
    client: DartClient,
    task: DownloadTask,
    filing: Filing,
    corp: Corporation,
    scraper: "LegacyDartScraper",
) -> Optional[bool]:
    """
    단일 공시 문서 다운로드 처리.

    흐름:
      1. OpenDART document.xml API → ZIP 다운로드
      2. 014(파일없음) 오류 시 → LegacyDartScraper 폴백 (dart.fss.or.kr 웹 뷰어)
      3. 020(API 사용량 소진) → 즉시 종료 / 013(문서 없음) → skipped
      4. 일시적 서버 오류 → failed (재시도 가능)

    반환: True=completed, False=failed, None=skipped
    """
    # ── 상태 → downloading ───────────────────────────────────
    with get_session() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.rcept_no == task.rcept_no)
            .values(
                status="downloading",
                attempts=func.coalesce(DownloadTask.attempts, 0) + 1,
                last_attempt_at=datetime.utcnow(),
            )
        )

    try:
        # ── ZIP 다운로드 ─────────────────────────────────────
        zip_bytes = client.get_document_zip(task.rcept_no)

        # DART는 오류 시 XML 에러 메시지를 반환 (ZIP 매직 바이트로 구분)
        if zip_bytes[:2] != b"PK":
            status_code, message = _parse_dart_xml_error(zip_bytes)
            err_msg = f"DART 오류 [{status_code}]: {message}"

            if status_code == "014":
                # ── 014: 파일없음 → 먼저 표준 XBRL 원문(ifrs.do) 시도, 없으면 웹 뷰어(레거시) 폴백 ──
                if _try_xbrl_instance_fallback(scraper, task, filing, corp):
                    return True
                return _try_legacy_fallback(scraper, task, filing, corp, err_msg)

            elif status_code == "020":
                # ── 020: API 일일 사용량 소진 → 즉시 종료 ────────
                logger.error(f"  ✋ DART API 사용량 소진(020) — 다운로드 중단: {message}")
                raise DartApiQuotaError(message)

            elif status_code == "013":
                # ── 013: 문서 자체가 없음 → skipped ──────────────
                logger.warning(f"  ↷ 문서 없음 → skipped: {err_msg}")
                _mark_skipped(task.rcept_no, err_msg)
                return None

            else:
                # ── 그 외 오류: 일시적 서버 문제 가능 → failed ───
                raise ValueError(err_msg)

        # ── ZIP 파싱 → 파일 선택 및 저장 ─────────────────────
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            best = _pick_best_file_by_size(zf)
            if best is None:
                # 인식 가능한 형식 없음 — 재시도 무의미하므로 skipped 처리
                all_exts = [Path(i.filename).suffix for i in zf.infolist()]
                logger.warning(f"  ↷ 처리 불가 형식 → skipped: {all_exts}")
                with get_session() as session:
                    session.execute(
                        update(DownloadTask)
                        .where(DownloadTask.rcept_no == task.rcept_no)
                        .values(
                            status="skipped",
                            last_error=f"미지원 파일 형식: {all_exts}",
                        )
                    )
                return None  # skipped

            # ── HWP/HTML 전용 ZIP: 파싱 불가 → 레거시 PDF 폴백 우선 ──
            # ZIP에 xml/pdf가 없고 hwp/html만 있으면(구형 공시), 웹뷰어에서
            # PDF를 먼저 시도한다. 실패 시 원본(hwp/html)을 그대로 보존.
            best_ext = Path(best.filename).suffix.lower()
            has_parseable = any(
                Path(i.filename).suffix.lower() in (".xml", ".xbrl", ".pdf")
                for i in zf.infolist()
            )
            if not has_parseable and best_ext in (".hwp", ".html", ".htm", ".zip"):
                logger.info(f"  ↷ 파싱 불가 형식({best_ext}) → 레거시 PDF 폴백 시도")
                try:
                    content, fmt = scraper.fetch(task.rcept_no)
                except Exception as e:
                    content, fmt = None, None
                    logger.debug(f"  레거시 fetch 오류: {e}")
                if content and fmt == "pdf":
                    dest_dir  = _build_file_path(corp, filing)
                    dest_path = dest_dir / f"{task.rcept_no}.pdf"
                    tmp_path  = TMP_DIR / f"{task.rcept_no}.pdf"
                    tmp_path.write_bytes(content)
                    shutil.move(str(tmp_path), dest_path)
                    fsize = dest_path.stat().st_size
                    logger.success(
                        f"  ✓ 저장 완료 [legacy PDF]: "
                        f"{dest_path.relative_to(RAW_REPORT_DIR)} ({fsize / 1024:.0f} KB)"
                    )
                    _mark_completed(task.rcept_no, dest_path, "pdf", fsize)
                    return True
                logger.info(f"  ↷ 레거시 PDF 폴백 실패 → 원본 형식({best_ext}) 보존")

            ext = Path(best.filename).suffix.lower() or ".bin"
            fmt_note = " [iXBRL]" if ext == ".xml" else ""
            dest_dir  = _build_file_path(corp, filing)
            dest_path = dest_dir / f"{task.rcept_no}{ext}"

            # 이미 완전히 다운로드된 파일이면 스킵
            if dest_path.exists() and dest_path.stat().st_size == best.file_size:
                logger.debug(f"  이미 존재 (동일 크기) → 스킵: {dest_path.name}")
                _mark_completed(task.rcept_no, dest_path, ext, best.file_size)
                return True

            # 압축 해제 → 저장 (primary)
            tmp_path = TMP_DIR / f"{task.rcept_no}{ext}"
            with zf.open(best) as src, open(tmp_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            shutil.move(str(tmp_path), dest_path)

            # ── PDF: 나머지 PDF 파일도 모두 저장 (병렬 재무제표 탐색용) ──
            # DART 구형 보고서는 재무제표가 별첨 PDF로 분리된 경우 있음
            # 형식: {rcept_no}_p2.pdf, {rcept_no}_p3.pdf …
            if ext == ".pdf":
                other_pdfs = [
                    i for i in zf.infolist()
                    if i.filename.lower().endswith(".pdf") and i != best
                ]
                for n, extra_info in enumerate(other_pdfs, 2):
                    extra_path = dest_dir / f"{task.rcept_no}_p{n}.pdf"
                    if extra_path.exists():
                        continue
                    tmp_extra = TMP_DIR / f"{task.rcept_no}_p{n}.pdf"
                    with zf.open(extra_info) as src, open(tmp_extra, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    shutil.move(str(tmp_extra), extra_path)
                if other_pdfs:
                    logger.debug(
                        f"  + 별첨 PDF {len(other_pdfs)}개 추가 저장 "
                        f"(_p2~_p{len(other_pdfs)+1})"
                    )

        file_size = dest_path.stat().st_size
        logger.success(
            f"  ✓ 저장 완료{fmt_note}: {dest_path.relative_to(RAW_REPORT_DIR)} "
            f"({file_size / 1024 / 1024:.1f} MB)"
        )
        _mark_completed(task.rcept_no, dest_path, ext.lstrip("."), file_size)

        # 다운로드 완료 후 짧은 대기 (서버 부하 경감)
        if MIN_DOWNLOAD_INTERVAL > 0:
            import time
            time.sleep(MIN_DOWNLOAD_INTERVAL)

        return True

    except DailyQuotaReached:
        # API 사용량 소진(서버 020) 또는 클라이언트 일일 한도 도달 —
        # 상위 루프(run_downloads)로 전파해 즉시 종료 (task를 failed로 기록하지 않음)
        raise
    except Exception as e:
        err_msg = str(e)[:500]
        logger.warning(f"  ✗ 다운로드 실패: {err_msg}")
        with get_session() as session:
            session.execute(
                update(DownloadTask)
                .where(DownloadTask.rcept_no == task.rcept_no)
                .values(status="failed", last_error=err_msg)
            )
        return False


def _mark_completed(
    rcept_no: str,
    dest_path: Path,
    file_type: str,
    file_size: int,
    parser_track: Optional[str] = None,
    dcm_no: Optional[str] = None,
) -> None:
    """다운로드 성공 시 DB 업데이트.

    parser_track/dcm_no는 XBRL 원문 폴백(_try_xbrl_instance_fallback) 전용 —
    기존 호출부는 넘기지 않으므로 해당 컬럼은 그대로 NULL 유지(회귀 없음).
    """
    values = dict(
        status="completed",
        file_path=str(dest_path),
        file_type=file_type.lstrip("."),
        file_size=file_size,
        completed_at=datetime.utcnow(),
    )
    if parser_track is not None:
        values["parser_track"] = parser_track
    if dcm_no is not None:
        values["dcm_no"] = dcm_no

    with get_session() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.rcept_no == rcept_no)
            .values(**values)
        )
