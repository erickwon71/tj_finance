"""PDF-only 2015+ 백로그 — ifrs.do XBRL 원문 재시도 회수 (2026-08-11).

배경: `docs/plans/pdf_only_parser_plan_2026-08-11.md` Phase 1 실측(§1-2) 중 발견 —
2015+ "PDF-only"(document.xml 014) 2,104건 표본 40건을 `_try_xbrl_instance_fallback()`
(ifrs.do)로 재시도했더니 **82.5%가 실제로는 구조화 XBRL 회수 가능**했다. 이 필링들이
`download_tasks.status='pdf'`로 굳어진 이유는 이 폴백 함수(`docs/plans/
xbrl_instance_parser_2026-08-05.md`, 2026-08-06 배포)가 신설되기 **이전에** 다운로드됐고,
이후 한 번도 재시도된 적이 없기 때문 — 새 파서가 아니라 **기존 파이프라인 재실행**으로
해소되는 문제다. 이 스크립트는 `scripts/backfill_xbrl_phase5.py`(5건 파일럿, 완료)와
동일한 패턴(① pending 리셋 → ② run_downloads → ③ sync_xbrl_instance_lines → ④ 검증)을
2015+ PDF-only 전체(2,104건, pre-2015는 실측상 0% 회수라 제외)로 확장한다.

주의(실행 전 반드시 읽을 것):
  - **오래 걸린다** — 실측 기준 rcept 당 opendart 1콜(1초 간격) + 회수 실패 시 dart.fss.or.kr
    웹 스크래핑 최대 2콜(2초 간격) 추가. 2,104건 전체면 **2~3시간 예상**. 사용자 터미널에서
    직접 실행 권장(백그라운드/nohup 등으로 걸어두고 다른 작업 병행 가능).
  - DART API 일일 사용량(020) 소진 시 `run_downloads()`가 자동 중단하고 그 시점까지 결과를
    반환한다 — 재실행하면 남은 pending 건부터 이어서 처리(멱등, 이미 완료된 건 재시도 안 함).
  - 회수 성공 시 `download_tasks.file_type`이 'pdf' → 'xbrl_zip'으로 갱신되고 file_path도
    xbrl zip 경로로 바뀐다. **기존에 받아뒀던 PDF 원본 파일 자체는 디스크에서 지워지지
    않는다**(DB가 더는 참조하지 않을 뿐 — 데이터 손실 아님, 필요하면 나중에 별도 정리).
  - `--limit N`으로 소규모 파일럿 먼저 돌려보는 것을 권장(예: 50건으로 회수율 재확인 후 전체
    실행).

실행 (파일럿 50건 먼저 권장):
  .venv/bin/python scripts/backfill_pdf_only_2015plus_xbrl_recovery.py --limit 50

전체 실행:
  .venv/bin/python scripts/backfill_pdf_only_2015plus_xbrl_recovery.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

_TARGET_SQL = text("""
    WITH filing_types AS (
      SELECT f.rcept_no, f.corp_code,
             bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
      FROM filings f
      JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
      JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
      WHERE f.filed_at >= '2015-01-01'
      GROUP BY f.rcept_no, f.corp_code
    )
    SELECT ft.rcept_no, ft.corp_code
    FROM filing_types ft
    WHERE NOT ft.has_xml
      AND EXISTS (
        SELECT 1 FROM download_tasks dt2
        WHERE dt2.rcept_no = ft.rcept_no AND dt2.file_type = 'pdf' AND dt2.status = 'completed'
      )
    ORDER BY ft.rcept_no
""")


def _targets(limit: int | None) -> list[tuple[str, str]]:
    with get_session() as session:
        rows = session.execute(_TARGET_SQL).fetchall()
    if limit:
        rows = rows[:limit]
    return [(r[0], r[1]) for r in rows]


def _reset_pending(rcepts: list[str]) -> int:
    with get_session() as session:
        result = session.execute(
            text("""
                UPDATE download_tasks
                   SET status = 'pending',
                       last_error = 'PDF-only 2015+ ifrs.do 회수 재시도 (2026-08-11)'
                 WHERE rcept_no = ANY(:r) AND status = 'completed' AND file_type = 'pdf'
            """),
            {"r": rcepts},
        )
        session.commit()
        return result.rowcount


def _verify(rcepts: list[str]) -> None:
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT dt.file_type, dt.status, count(*)
                FROM download_tasks dt
                WHERE dt.rcept_no = ANY(:r)
                GROUP BY 1, 2 ORDER BY 1, 2
            """),
            {"r": rcepts},
        ).fetchall()
    logger.info("── 다운로드 결과 분포(file_type x status) ──")
    for r in rows:
        logger.info(f"  file_type={str(r[0]):<10} status={r[1]:<10} count={r[2]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                     help="파일럿용 상한 건수(미지정 시 2015+ PDF-only 전체)")
    ap.add_argument("--skip-sync", action="store_true",
                     help="다운로드만 하고 report_lines 적재(sync_xbrl_instance_lines)는 건너뜀")
    args = ap.parse_args()

    targets = _targets(args.limit)
    if not targets:
        logger.info("대상 없음 — 이미 전부 처리됐거나 조건에 맞는 건이 없습니다.")
        return 0
    rcepts = [t[0] for t in targets]
    corps = sorted({t[1] for t in targets})
    logger.info(f"대상: {len(rcepts)}건 / {len(corps)}개사")

    n = _reset_pending(rcepts)
    logger.info(f"① download_tasks pending 리셋: {n}건")

    from collector.downloader import run_downloads

    logger.info("② run_downloads(only_corp_codes=...) 실행 — 시간이 오래 걸립니다")
    dl_stats = run_downloads(only_corp_codes=corps)
    logger.info(f"   다운로드 결과: {dl_stats}")

    if not args.skip_sync:
        from collector.xbrl_instance_lines_sync import sync_xbrl_instance_lines

        # ★2026-08-11 발견: 이 스크립트의 대상 스코프는 filed_at>=2015-01-01(접수일) 기준인데,
        # sync_xbrl_instance_lines()의 기본 FY_MIN=2015는 fiscal_year(회계연도) 기준 —
        # 서로 다른 필드다. 연초에 접수된 전기(fiscal_year<2015, 심지어 2009도 관측됨) 분기/
        # 반기보고서가 다수 섞여 있어 기본값 그대로면 이런 필링이 report_lines에 조용히
        # 누락된다(50건 파일럿 실측: xbrl_zip 회수 44건 중 39건이 fiscal_year<2015).
        # note_lines_sync.py::FY_MIN 이 겪었던 것과 동일 패턴(PARSING_RULES R13) — 여기서는
        # 공용 모듈 상수를 건드리지 않고 이 호출에서만 명시적으로 낮춘다(다른 호출부 영향 없음).
        # extract_report_lines_xbrl() 자체가 'ifrs-full' 네임스페이스 없는 문서는 안전하게
        # skip(빈 리스트 반환)하므로, year_min을 낮춰도 K-GAAP 전용 XBRL을 잘못 적재할 위험은
        # 없다 — 그냥 더 넓게 "시도"할 뿐이다.
        logger.info("③ sync_xbrl_instance_lines(recheck=False, year_min=1999) 실행")
        sync_stats = sync_xbrl_instance_lines(corps=corps, recheck=False, year_min=1999)
        logger.info(f"   적재 결과: {sync_stats}")
    else:
        logger.info("③ --skip-sync 지정됨 — report_lines 적재는 건너뜀")

    logger.info("④ 검증")
    _verify(rcepts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
