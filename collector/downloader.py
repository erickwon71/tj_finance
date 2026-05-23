"""
보고서 파일 다운로더
Step 3: download_tasks 테이블의 pending/failed 건을 순서대로 처리

처리 흐름:
  1. DART document.xml API → ZIP 다운로드
  2. ZIP 압축 해제 → 파일 유형 분류 (pdf > html > hwp > xml(iXBRL) > zip)
  3. raw_report/{market}/{corp_code}_{corp_name}/{report_type}/{fiscal_year}/ 에 저장
  4. download_tasks 상태 업데이트

DART 제출 형식:
  - ~2023: PDF 또는 HWP 위주
  - 2024~: iXBRL(.xml) 위주 — 분기/반기보고서는 사실상 전면 전환됨
    (XML 안에 HTML + XBRL 태그가 내장된 인라인 XBRL 형식)

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
from sqlalchemy import select, update

from collector.config import (
    RAW_REPORT_DIR, TMP_DIR,
    MAX_DOWNLOAD_ATTEMPTS, MIN_DOWNLOAD_INTERVAL,
)
from collector.dart_client import DartClient, DartApiError
from collector.db import get_session
from collector.models import Corporation, Filing, DownloadTask, CollectionRun


# ── 파일 확장자 우선순위 ─────────────────────────────────────────────
# xml: DART iXBRL 형식 (2024년~ 분기/반기보고서 주력 제출 형식)
#      HTML + XBRL 태그가 내장된 인라인 XBRL — 브라우저에서 바로 열림
_EXT_PRIORITY = [".pdf", ".html", ".htm", ".hwp", ".xml", ".xbrl", ".zip"]

# 여러 개일 때 가장 큰 파일(본문)을 선택할 확장자
_PICK_LARGEST_EXTS = {".pdf", ".xml", ".xbrl"}


def _pick_best_file_by_size(zf: zipfile.ZipFile) -> Optional[zipfile.ZipInfo]:
    """
    ZIP 내에서 우선순위에 따라 최적 파일 선택.
    - pdf / xml / xbrl : 여러 개면 가장 큰 파일 (본문 document)
    - html / hwp / zip : 첫 번째 매칭
    ZIP에 아무것도 없으면 None 반환 → 호출부에서 'skipped' 처리.
    """
    infos = zf.infolist()
    for ext in _EXT_PRIORITY:
        candidates = [i for i in infos if i.filename.lower().endswith(ext)]
        if candidates:
            if ext in _PICK_LARGEST_EXTS:
                return max(candidates, key=lambda i: i.file_size)
            return candidates[0]
    return None


def _handle_non_zip_response(rcept_no: str, raw: bytes) -> None:
    """
    DART가 ZIP 대신 XML 에러를 반환했을 때 처리.

    DART 에러 응답 예시:
      <?xml version="1.0"?>
      <result><status>020</status><message>문서가 존재하지 않습니다.</message></result>

    - 문서 없음(013·014·020) → skipped (재시도 무의미)
    - 그 외 DART 에러    → failed  (일시적 서버 문제일 수 있음)
    - XML 파싱 불가      → failed  (예외 raise)
    """
    import xml.etree.ElementTree as ET

    # DART XML 에러 상태코드 중 '문서 없음'으로 확정되는 것
    NO_DOC_STATUSES = {"013", "014", "020"}

    # <?xml 또는 <result 로 시작하면 DART XML 에러 응답으로 간주
    if raw[:1] == b"<":
        try:
            root = ET.fromstring(raw.decode("utf-8", errors="replace"))
            status  = (root.findtext("status")  or "").strip()
            message = (root.findtext("message") or "알 수 없는 오류").strip()
            err_msg = f"DART 오류 [{status}]: {message}"
        except ET.ParseError:
            err_msg = f"비ZIP 응답 (XML 파싱 실패, 첫 50바이트: {raw[:50]})"
            status  = ""

        if status in NO_DOC_STATUSES:
            # 문서가 DART 서버에 없음 → skipped (재시도해도 소용없음)
            logger.warning(f"  ↷ 문서 없음 → skipped: {err_msg}")
            with get_session() as session:
                session.execute(
                    update(DownloadTask)
                    .where(DownloadTask.rcept_no == rcept_no)
                    .values(status="skipped", last_error=err_msg)
                )
            return  # 정상 종료 (skipped)

        # 그 외 DART 에러 (일시적 오류 가능) → 예외 raise → failed 처리
        raise ValueError(err_msg)

    # 전혀 예상치 못한 응답
    raise ValueError(f"ZIP이 아닌 응답 수신 (첫 4바이트: {raw[:4].hex()})")


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
    client = DartClient()
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
                    DownloadTask.attempts < MAX_DOWNLOAD_ATTEMPTS,
                    Filing.is_final == True,
                )
                .order_by(
                    Filing.corp_code.asc(),      # 기업별로 묶어서 처리
                    Filing.fiscal_year.desc(),   # 기업 내에서는 최신 연도부터
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

            success = _download_one(client, task, filing, corp)
            if success:
                stats["completed"] += 1
            else:
                stats["failed"] += 1

        # 실행 이력
        with get_session() as session:
            run.ended_at  = datetime.utcnow()
            run.total     = stats["total_queued"]
            run.completed = stats["completed"]
            run.failed    = stats["failed"]
            run.api_calls = stats["completed"] + stats["failed"]
            session.add(run)

        logger.success(
            f"다운로드 완료 — "
            f"성공 {stats['completed']:,} / 실패 {stats['failed']:,} / "
            f"전체 {stats['total_queued']:,}건"
        )
        return stats

    finally:
        client.close()


def _download_one(
    client: DartClient,
    task: DownloadTask,
    filing: Filing,
    corp: Corporation,
) -> bool:
    """
    단일 공시 문서 다운로드 처리.
    반환: 성공 여부
    """
    # ── 상태 → downloading ───────────────────────────────────
    with get_session() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.rcept_no == task.rcept_no)
            .values(
                status="downloading",
                attempts=DownloadTask.attempts + 1,
                last_attempt_at=datetime.utcnow(),
            )
        )

    try:
        # ── ZIP 다운로드 ─────────────────────────────────────
        zip_bytes = client.get_document_zip(task.rcept_no)

        # DART는 오류 시 XML 에러 메시지를 반환하는 경우가 있음 (ZIP 매직 바이트 확인)
        if zip_bytes[:2] != b"PK":
            _handle_non_zip_response(task.rcept_no, zip_bytes)
            return False  # skipped 처리 후 종료 (예외는 _handle_non_zip_response 내부에서 raise)

        # ── ZIP 파싱 → 최적 파일 선택 ────────────────────────
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
                return False

            ext = Path(best.filename).suffix.lower() or ".bin"
            fmt_note = " [iXBRL]" if ext == ".xml" else ""
            dest_dir  = _build_file_path(corp, filing)
            dest_path = dest_dir / f"{task.rcept_no}{ext}"

            # 이미 완전히 다운로드된 파일이면 스킵
            if dest_path.exists() and dest_path.stat().st_size == best.file_size:
                logger.debug(f"  이미 존재 (동일 크기) → 스킵: {dest_path.name}")
                _mark_completed(task.rcept_no, dest_path, ext, best.file_size)
                return True

            # 압축 해제 → 저장
            tmp_path = TMP_DIR / f"{task.rcept_no}{ext}"
            with zf.open(best) as src, open(tmp_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            # 원자적 이동 (부분 파일 방지)
            shutil.move(str(tmp_path), dest_path)

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
) -> None:
    """다운로드 성공 시 DB 업데이트"""
    with get_session() as session:
        session.execute(
            update(DownloadTask)
            .where(DownloadTask.rcept_no == rcept_no)
            .values(
                status="completed",
                file_path=str(dest_path),
                file_type=file_type.lstrip("."),
                file_size=file_size,
                completed_at=datetime.utcnow(),
            )
        )
