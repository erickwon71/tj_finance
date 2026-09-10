"""Track C 잔여 93건(fail19+missing74) 소급 백필 — reconcile() 기반 재배선(R82) 실행.

배경(2026-09-07, 사용자 지시 "93건 전체 소급 백필 진행하고 검증 해봐"):
`collector/pdf_lines_sync.py::recover_one()`가 이제 `reconcile()`(HTML→PDF
T1/T2/T3)을 쓴다(§8-15, R82). 이 93건은 fail19+missing74 검증대장 — 대부분
**이미 report_lines 가 존재**(옛 PDF-only 방식으로 채워졌으나 그랜드토탈이
틀리거나 빠져있는 상태)한다. `sync_pdf_recovery()`의 후보 SQL은 `NOT EXISTS
report_lines` 라 이 93건 대부분을 못 잡는다(기존 `backfill_pdf_multiline_195_
2026-09-06.py`류와 동일 이유) — 그래서 `recover_one()`을 직접 호출한다.

`scripts/scan_html_viewer_layout_93_2026-09-07.py`의 SAMPLES(고유 rcept 93건,
중복 제거)를 그대로 재사용하고, fiscal_year/period는 `filings` 테이블에서 조회.

usage:
    python scripts/backfill_track_c_93_reconcile_2026-09-07.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from collector.legacy_downloader import LegacyDartScraper  # noqa: E402
from collector.pdf_lines_sync import recover_one  # noqa: E402
from fin2.extract.report_lines import store_report_lines  # noqa: E402
from fin2.extract.reconcile_store import persist_unresolved  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "scan93", str(Path(__file__).resolve().parent / "scan_html_viewer_layout_93_2026-09-07.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SAMPLES = _mod.SAMPLES


def _unique_targets() -> list[tuple[str, str, str]]:
    """(corp_code, name, rcept_no) 중복 제거, SAMPLES 순서 보존."""
    seen: set[tuple[str, str]] = set()
    out = []
    for corp, name, rcept, _cat in SAMPLES:
        key = (corp, rcept)
        if key in seen:
            continue
        seen.add(key)
        out.append((corp, name, rcept))
    return out


def main() -> None:
    targets = _unique_targets()
    logger.info(f"[backfill93] 대상 {len(targets)}건")

    with get_session() as s:
        fy_map = {}
        for corp, name, rcept in targets:
            row = s.execute(text("SELECT fiscal_year, fiscal_period FROM filings WHERE rcept_no=:r"),
                             {"r": rcept}).fetchone()
            if row:
                fy_map[rcept] = row

    out = {"total": len(targets), "no_filing_row": 0, "bases_html": 0, "bases_pdf": 0,
           "bases_unresolved": 0, "rows": 0, "dq_rows": 0, "errors": 0}
    error_detail = []

    scraper = LegacyDartScraper()
    try:
        with get_session() as session:
            for i, (corp, name, rcept) in enumerate(targets, 1):
                if rcept not in fy_map:
                    out["no_filing_row"] += 1
                    logger.warning(f"[backfill93] {corp} {name} {rcept} — filings 행 없음, 스킵")
                    continue
                fy, fp = fy_map[rcept]
                try:
                    lines, results = recover_one(scraper, rcept, corp, fy, fp)

                    for r in results:
                        if r.decision == "html":
                            out["bases_html"] += 1
                        elif r.decision == "pdf":
                            out["bases_pdf"] += 1
                        else:
                            out["bases_unresolved"] += 1

                    if lines:  # store_report_lines()는 delete-then-insert — 빈 리스트면 호출 안 함
                        out["rows"] += store_report_lines(session, rcept, lines)

                    out["dq_rows"] += persist_unresolved(
                        results, session, corp_code=corp, rcept_no=rcept,
                        report_fiscal_year=fy, report_fiscal_period=fp,
                        source_pipeline="track_c_backfill",
                    )
                except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                    out["errors"] += 1
                    session.rollback()
                    error_detail.append((corp, name, rcept, type(exc).__name__, str(exc)[:150]))
                    logger.warning(f"[backfill93] {corp} {name} {rcept} 실패: {type(exc).__name__}: {exc}")
                    continue

                if i % 20 == 0:
                    session.commit()
                    logger.info(f"[backfill93] … {i}/{len(targets)} 처리")
            session.commit()
    finally:
        scraper.close()

    logger.info(f"[backfill93] 완료: {out}")
    print("\n=== RESULT ===")
    print(out)
    if error_detail:
        print("\n=== ERRORS ===")
        for e in error_detail:
            print(e)


if __name__ == "__main__":
    main()
