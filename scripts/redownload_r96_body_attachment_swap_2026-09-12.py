"""R96 재다운로드 — census(`scripts/census_r96_body_attachment_swap_2026-09-12.py`)로
확인된 "감사보고서가 본문으로 잘못 저장된" 484건을 실제 `_download_one()`으로 다시
받아 수정된 `_pick_best_file_by_size()`가 본문을 정확히 채택하게 한다 (2026-09-12).

## 범위
`manual_review/_r96_census_2026-09-12/still_wrong_on_nas.csv`(484건, 353개사) —
NAS 원본과 직접 대조까지 마친 "진짜 미해결" 목록. 양지사·티로보틱스(이미 6월에
수동으로 고쳐진 2건)는 이 목록에 없다.

## 왜 `_download_one()`을 직접 재사용하는가
`run_downloads()`는 `status IN (pending,failed)`인 행만 골라서 처리하는데, 이
484건은 `status='completed'`(다만 내용이 틀림)라 그 큐에 안 걸린다. `_download_one`은
상태를 안 가리고(시작할 때 무조건 downloading→처리) 다시 받아오므로 이걸 직접
호출한다 — 새 대체 로직을 만들지 않고 기존 다운로드 경로(재시도/014·020·013 처리,
`_mark_completed`의 `completed_at` 갱신 포함)를 그대로 재사용해 회귀 위험을 줄인다.

## `completed_at` 갱신 확인 (2026-06 라이브 재다운로드 때 놓쳤던 부분)
`_mark_completed()`가 항상 `completed_at=datetime.utcnow()`을 쓰므로, 이번엔
`scripts/sync_storage_mirror.py`(증분, `completed_at >= now()-48h` 기준)가 자동으로
잡는다 — 별도 전체스캔 없이 재다운로드 직후 그 스크립트를 한 번 돌리면 SD까지 반영됨.

## ★report_lines 재적재는 이 스크립트 범위 밖
파일(원문)만 고친다. `report_lines`/`report_tables` 재적재는 사용자 지시대로
지금 진행 중인 전사 재적재(`scripts/reload_report_lines_2015plus_2026-09-12.py`)
완료 후 별도로 한다 — 여기서 자동으로 하지 않는다.

## 사용
    python scripts/redownload_r96_body_attachment_swap_2026-09-12.py --dry-run
    python scripts/redownload_r96_body_attachment_swap_2026-09-12.py --limit 10   # 시험
    python scripts/redownload_r96_body_attachment_swap_2026-09-12.py              # 본실행(484건)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from collector.dart_client import DartClient
from collector.db import get_session
from collector.downloader import DartApiQuotaError, _download_one
from collector.legacy_downloader import LegacyDartScraper
from sqlalchemy import select

from collector.models import Corporation, DownloadTask, Filing

_CENSUS_CSV = Path("manual_review/_r96_census_2026-09-12/still_wrong_on_nas.csv")
_BODY_KEYWORDS = ("사업보고서", "반기보고서", "분기보고서")
_DOC_NAME_RE_BYTES = re.compile(rb"<DOCUMENT-NAME[^>]*>([^<]*)</DOCUMENT-NAME>")


def _decode_doc_name(raw: bytes) -> str | None:
    """바이트 그대로 매칭 후 매칭 구간만 디코드 — 고정길이 절단 디코드 버그
    ([[held-zero-line-filing-triage-sibling-check-2026-09-12]] 계열, census
    스크립트와 동일 방식) 재발 방지. 2011년대 다수가 EUC-KR이라 폴백 필수."""
    m = _DOC_NAME_RE_BYTES.search(raw)
    if not m:
        return None
    seg = m.group(1)
    for enc in ("utf-8", "euckr"):
        try:
            return seg.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return seg.decode("utf-8", errors="replace").strip()


def _load_target_rcepts(limit: int | None) -> list[str]:
    with open(_CENSUS_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rcepts = [r["rcept_no"] for r in rows]
    return rcepts[:limit] if limit else rcepts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="대상 상한(시험용)")
    ap.add_argument("--dry-run", action="store_true", help="대상 개수만 확인, 다운로드 안 함")
    args = ap.parse_args()

    rcepts = _load_target_rcepts(args.limit)
    logger.info(f"재다운로드 대상 {len(rcepts):,}건 ({_CENSUS_CSV})")
    if args.dry_run:
        logger.info("--dry-run — 종료")
        return

    client = DartClient()
    scraper = LegacyDartScraper()
    n_fixed = n_still_wrong = n_failed = n_skipped = 0
    still_wrong: list[str] = []
    failed: list[str] = []

    try:
        for i, rcept_no in enumerate(rcepts, start=1):
            with get_session() as s:
                task = s.scalars(
                    select(DownloadTask).where(DownloadTask.rcept_no == rcept_no)
                ).first()
                filing = s.get(Filing, rcept_no)
                corp = s.get(Corporation, filing.corp_code) if filing else None
            if task is None or filing is None or corp is None:
                logger.warning(f"[{i}/{len(rcepts)}] {rcept_no} — DB row 없음, 스킵")
                n_skipped += 1
                continue

            logger.info(f"[{i}/{len(rcepts)}] {corp.corp_name} {filing.fiscal_year}"
                        f"{filing.fiscal_period} {rcept_no}")
            try:
                result = _download_one(client, task, filing, corp, scraper)
            except DartApiQuotaError:
                logger.warning(f"  ✋ 일일 API 한도 도달 — 중단 "
                                f"(완료 {n_fixed}/{len(rcepts)})")
                break

            if result is not True:
                n_failed += 1
                failed.append(rcept_no)
                continue

            # ── 검증: 이번엔 진짜 본문으로 고쳐졌는지 즉시 확인 ──
            with get_session() as s:
                fresh_task = s.scalars(
                    select(DownloadTask).where(DownloadTask.rcept_no == rcept_no)
                ).first()
                fresh_path = fresh_task.file_path
            try:
                with open(fresh_path, "rb") as f:
                    head = f.read(4096)
            except OSError:
                head = b""
            doc_name = _decode_doc_name(head)
            if doc_name and any(kw in doc_name for kw in _BODY_KEYWORDS):
                n_fixed += 1
            else:
                n_still_wrong += 1
                still_wrong.append(rcept_no)
                logger.warning(f"  ⚠ 재다운로드했는데도 본문 아님(doc_name={doc_name!r}) "
                                f"— ZIP 자체에 본문이 없을 가능성(별도 조사 필요): {rcept_no}")

    finally:
        client.close()
        scraper.close()

    logger.success(f"완료 — 고쳐짐 {n_fixed:,} · 여전히 잘못됨 {n_still_wrong:,} · "
                    f"다운로드실패 {n_failed:,} · 스킵 {n_skipped:,} / 전체 {len(rcepts):,}")

    remaining = still_wrong + failed
    if remaining:
        out = Path("manual_review/_r96_census_2026-09-12/still_wrong_after_redownload.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "category", "dart_link"])
            for rc in still_wrong:
                w.writerow([rc, "본문없음(재다운로드해도 첨부뿐)",
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rc}"])
            for rc in failed:
                w.writerow([rc, "다운로드실패",
                            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rc}"])
        logger.info(f"미해결 {len(remaining):,}건 → {out} (다음 단계: 형제필링에 "
                    f"is_final=True + 실데이터 있는지 확인 후, 없으면 진짜 재조사)")


if __name__ == "__main__":
    main()
