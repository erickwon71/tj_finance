"""Category C fy1999~2003 절단분 PDF 복구 — 전량 실행 (2026-09-03, 1회성).

배경: `docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3(2026-09-03 후속).
DART `document.xml` API가 결정적으로 잘린 응답을 준 fy1999~2003 필링을 DART 웹 뷰어
(PDF)로 재수집해 `report_lines`에 적재한다. `collector/pdf_lines_sync.py::sync_pdf_recovery()`
가 실제 작업(다운로드→PDF파싱→저장)을 한다 — 이 스크립트는 그 실행 진입점 + 진행 로그다.

소요시간: DART 웹 쓰로틀링(요청당 ~2초 × 필링당 3요청) 때문에 필링당 ~7~8초, 대상
~6,592건 기준 **약 13~14시간**. 장시간 작업이라 사용자가 직접 터미널에서 실행한다
(백그라운드+로그 버전은 아래 안내 참고).

멱등: `store_report_lines`가 rcept 단위 delete-then-insert라 중단 후 재실행해도 안전
(이미 적재된 rcept는 다시 report_lines가 0행인 것만 대상이므로 자동으로 재시도 대상에서
빠진다 — sync_pdf_recovery의 _TRUNCATED_CANDIDATES_SQL이 매번 "report_lines 없음"만 재조회).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.pdf_lines_sync import sync_pdf_recovery

CORP_LIST_PATH = "/tmp/backfill_c_corps_2026-09-01.txt"


def main() -> None:
    corps = Path(CORP_LIST_PATH).read_text().split()
    print(f"[pdf-recovery] 시드 corp 수: {len(corps)}")
    t0 = time.time()
    out = sync_pdf_recovery(corps)
    elapsed = time.time() - t0
    print(f"[pdf-recovery] 완료 — {elapsed/3600:.1f}시간")
    print(f"[pdf-recovery] 결과: {out}")


if __name__ == "__main__":
    main()
