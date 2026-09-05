"""(C)+(A-1)+(A-2) 백필 — Category C fy2004~2017 잔존 항목 1-b 중
"요약" 접두(C) + SECTION-3 서브헤딩 리셋(A-1: depth-aware 컨테이너 통짜블롭 버그,
A-2: normalize_dart_section_title 가나다 접두 미제거) 3건 수정분.

설계문서: `docs/plans/category_c_fy2004_2006_section3_and_summary_prefix_design_2026-09-05.md`

(A-3, 통짜-셀 레거시 표 포맷)은 이번 스코프 밖 — 정량화(§3)에서 확인된 대로 대부분
여전히 빈 결과를 낸다(정상, 재작업 아님). R69 백필 스크립트(`backfill_r69_legacy_
appendix_2026-09-05.py`)와 같은 패턴: 대상 전체에 `extract_report_lines()`를 다시
돌려 body>0행인 것만 저장한다(멱등 — rcept 단위 delete-then-insert).

R69 스크립트는 fy2007~2010(A) 를 스코프에서 뺐다("이번 수정으로 혜택이 없어 여전히
0행") — 이번엔 정확히 그 자리를 채운다. fy2004~2017 전체를 대상으로 재시도한다.

★ NAS(raw_report 심링크) 대신 SD 카드(dart_data) 경로로 치환해서 읽는다
(`feedback-bulk-read-use-sdcard` 메모리 — 대량 read 시 NAS SMB 는 느림).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (
    extract_report_lines, store_note_lines, store_report_lines, store_report_tables,
)

_NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"

_TARGETS_SQL = text(
    """
    SELECT f.corp_code, f.rcept_no, f.fiscal_year, f.fiscal_period, dt.file_path
    FROM download_tasks dt
    JOIN filings f ON f.rcept_no = dt.rcept_no
    WHERE dt.status = 'completed' AND dt.file_type IN ('xml', 'zip')
      AND f.fiscal_year BETWEEN 2004 AND 2017
      AND f.is_final = true
      AND f.report_type IN ('annual', 'half', 'quarter')
      AND NOT EXISTS (
          SELECT 1 FROM report_lines rl WHERE rl.rcept_no = f.rcept_no)
    ORDER BY f.corp_code, f.rcept_no
    """
)


def main() -> None:
    with get_session() as s:
        targets = s.execute(_TARGETS_SQL).fetchall()
    print(f"[A1A2C-backfill] 대상 {len(targets):,}건")

    n_ok = n_empty = n_err = n_missing_file = 0
    body_rows_total = note_rows_total = 0
    touched_corps: set[str] = set()
    t0 = time.time()

    with get_session() as session:
        for i, (corp, rcept, fy, fp, path) in enumerate(targets, 1):
            sd_path = path.replace(_NAS_PREFIX, _SD_PREFIX) if path.startswith(_NAS_PREFIX) else path
            p = Path(sd_path)
            if not p.exists():
                p = Path(path)  # SD 카드에 없으면 원래(NAS) 경로로 재시도
                if not p.exists():
                    n_missing_file += 1
                    continue
            try:
                lines = extract_report_lines(
                    str(p), rcept_no=rcept, corp_code=corp,
                    report_fiscal_year=fy, report_fiscal_period=fp,
                    include_notes=True,
                )
                note_rows_total += store_note_lines(session, rcept, lines)
                store_report_tables(session, rcept, lines)
                n_body = store_report_lines(session, rcept, lines)
                body_rows_total += n_body
                if n_body:
                    n_ok += 1
                    touched_corps.add(corp)
                else:
                    n_empty += 1
            except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                n_err += 1
                print(f"  ! {rcept} ({corp} fy{fy}{fp}): {type(e).__name__}: {e}")

            if i % 200 == 0:
                session.commit()
                elapsed = time.time() - t0
                print(f"  … {i}/{len(targets)} · 성공 {n_ok} · 빈결과 {n_empty} · "
                      f"오류 {n_err} · {elapsed:.0f}s", flush=True)
        session.commit()

    print(f"\n[A1A2C-backfill] 완료 — {time.time()-t0:.0f}s")
    print(f"  성공(body>0행): {n_ok:,} / 빈 결과(여전히 실패, A-3 등 스코프 밖): {n_empty:,} / "
          f"오류: {n_err} / 파일소실: {n_missing_file}")
    print(f"  body_rows 합계: {body_rows_total:,} · note_rows 합계: {note_rows_total:,}")
    print(f"  영향받은 corp 수: {len(touched_corps):,}")

    with open("/tmp/a1a2c_backfill_touched_corps.txt", "w") as f:
        f.write("\n".join(sorted(touched_corps)))
    print("  corp 목록 저장: /tmp/a1a2c_backfill_touched_corps.txt")


if __name__ == "__main__":
    main()
