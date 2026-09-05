"""R69(2026-09-05) 백필 — Category C fy2007~2017 (E)+(D)+(B) 대상 report_lines 재추출.

`docs/plans/category_c_legacy_appendix_variant_design_2026-09-05.md` 구현분.
`sync_layer2_lines`(corp 단위, 그 corp 의 year_min 이후 **전체 이력**을 훑음)는
이번 스코프엔 과함 — 대상은 이미 정확히 아는 rcept 4,794건뿐이라, 그 rcept들에만
`extract_report_lines`→`store_note_lines`/`store_report_tables`/`store_report_lines`를
직접 호출한다(내부적으로 쓰는 저장 함수는 `sync_layer2_lines`와 동일, 대상 선정만 다름).

fy2004~2006(버그 A, 이번 스코프 밖)은 애초에 후보에서 제외한다 — 이번 수정으로
혜택이 없어 재처리해도 여전히 0행이므로 시간 낭비.

멱등: rcept 단위 delete-then-insert(store_note_lines/store_report_lines 기존 계약) —
중단 후 재실행 안전(§`_LOADED_SQL`류 사전필터 없이 매번 전체 대상 재시도 — 대상이
4,794건으로 이미 작아 문제 없음).
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

_TARGETS_SQL = text(
    """
    SELECT f.corp_code, f.rcept_no, f.fiscal_year, f.fiscal_period, dt.file_path
    FROM download_tasks dt
    JOIN filings f ON f.rcept_no = dt.rcept_no
    WHERE dt.status = 'completed' AND dt.file_type IN ('xml', 'zip')
      AND f.fiscal_year BETWEEN 2007 AND 2017
      AND NOT EXISTS (
          SELECT 1 FROM report_lines rl
          WHERE rl.corp_code = f.corp_code AND rl.report_fiscal_year = f.fiscal_year
            AND rl.report_fiscal_period = f.fiscal_period)
    ORDER BY f.corp_code, f.rcept_no
    """
)


def main() -> None:
    with get_session() as s:
        targets = s.execute(_TARGETS_SQL).fetchall()
    print(f"[R69-backfill] 대상 {len(targets):,}건")

    n_ok = n_empty = n_err = n_missing_file = 0
    body_rows_total = note_rows_total = 0
    touched_corps: set[str] = set()
    t0 = time.time()

    with get_session() as session:
        for i, (corp, rcept, fy, fp, path) in enumerate(targets, 1):
            if not Path(path).exists():
                n_missing_file += 1
                continue
            try:
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=corp,
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

    print(f"\n[R69-backfill] 완료 — {time.time()-t0:.0f}s")
    print(f"  성공(body>0행): {n_ok:,} / 빈 결과(여전히 실패, 스코프 밖 등): {n_empty:,} / "
          f"오류: {n_err} / 파일소실: {n_missing_file}")
    print(f"  body_rows 합계: {body_rows_total:,} · note_rows 합계: {note_rows_total:,}")
    print(f"  영향받은 corp 수: {len(touched_corps):,}")

    with open("/tmp/r69_backfill_touched_corps.txt", "w") as f:
        f.write("\n".join(sorted(touched_corps)))
    print("  corp 목록 저장: /tmp/r69_backfill_touched_corps.txt")


if __name__ == "__main__":
    main()
