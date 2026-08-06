"""Phase 5 — XBRL 원문 파서 소급 백필 (docs/plans/xbrl_instance_parser_todo_2026-08-05.md).

대상 5건(자비스는 XBRL 자체가 없어 제외 — docs/qa/handoff_xml_parse_failure_xbrl_finding_2026-08-05.md §2):
  - 20250828000534  박셀바이오       2024H1
  - 20191118000002  웰킵스하이텍     2019Q3
  - 20191119000045  웰킵스하이텍     2019Q3
  - 20191119000058  웰킵스하이텍     2019Q3
  - 20260513000860  한화에어로스페이스 2026Q1

이 5건은 이미 `download_tasks.status='completed', file_type='pdf'`(document.xml 014 →
레거시 PDF 폴백)로 저장돼 있다. Phase 2에서 신설한 `_try_xbrl_instance_fallback()`이 아직
한 번도 이 rcept_no들에 적용된 적이 없으므로, status를 pending으로 되돌려 재다운로드시키면
이번엔 PDF보다 먼저 XBRL 원문(ifrs.do)을 시도한다.

흐름: ① status pending 리셋 → ② run_downloads(only_corp_codes=...) → ③
sync_xbrl_instance_lines(recheck=True) → ④ 결과 검증(report_lines unit_source='xbrl').

실행:
  .venv/bin/python scripts/backfill_xbrl_phase5.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

TARGET_RCEPTS = [
    "20250828000534",
    "20191118000002",
    "20191119000045",
    "20191119000058",
    "20260513000860",
]


def _reset_pending(rcepts: list[str]) -> int:
    with get_session() as session:
        result = session.execute(
            text(
                """
                UPDATE download_tasks
                   SET status = 'pending', last_error = 'Phase 5 XBRL 백필 재시도'
                 WHERE rcept_no = ANY(:r)
                """
            ),
            {"r": rcepts},
        )
        session.commit()
        return result.rowcount


def _corp_codes(rcepts: list[str]) -> list[str]:
    with get_session() as session:
        rows = session.execute(
            text("SELECT DISTINCT corp_code FROM filings WHERE rcept_no = ANY(:r)"),
            {"r": rcepts},
        ).fetchall()
    return [r[0] for r in rows]


def _verify(rcepts: list[str]) -> None:
    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT dt.rcept_no, dt.status, dt.file_type, dt.file_path,
                       (SELECT count(*) FROM report_lines rl
                         WHERE rl.rcept_no = dt.rcept_no AND rl.unit_source = 'xbrl') AS n_lines,
                       (SELECT count(*) FROM report_tables rt
                         WHERE rt.rcept_no = dt.rcept_no) AS n_tables
                  FROM download_tasks dt
                 WHERE dt.rcept_no = ANY(:r)
                 ORDER BY dt.rcept_no
                """
            ),
            {"r": rcepts},
        ).fetchall()
    logger.info("── 검증 결과 ──")
    for r in rows:
        logger.info(
            f"  {r.rcept_no}  status={r.status:<10} file_type={str(r.file_type):<10} "
            f"report_lines(xbrl)={r.n_lines:>4}  report_tables={r.n_tables:>4}"
        )


def main() -> int:
    n = _reset_pending(TARGET_RCEPTS)
    logger.info(f"① download_tasks pending 리셋: {n}건")

    corps = _corp_codes(TARGET_RCEPTS)
    logger.info(f"대상 corp_code: {corps}")

    from collector.downloader import run_downloads

    logger.info("② run_downloads(only_corp_codes=...) 실행")
    dl_stats = run_downloads(only_corp_codes=corps)
    logger.info(f"   다운로드 결과: {dl_stats}")

    from collector.xbrl_instance_lines_sync import sync_xbrl_instance_lines

    logger.info("③ sync_xbrl_instance_lines(recheck=True) 실행")
    sync_stats = sync_xbrl_instance_lines(corps=corps, recheck=True)
    logger.info(f"   적재 결과: {sync_stats}")

    logger.info("④ 검증")
    _verify(TARGET_RCEPTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
