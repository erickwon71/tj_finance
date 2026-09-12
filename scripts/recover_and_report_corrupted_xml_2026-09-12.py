#!/usr/bin/env python
"""원문 손상(리터럴 '?' 치환) 감지 → PDF/HTML 복구 시도 → **사람이 확인할 수 있게 보고**.

배경: `docs/plans/parser_source_fallback_cascade_design_2026-09-12.md`. 솔트웨어
20220802000208 실측(2026-09-12) — DART OpenDART `document.xml` archive 자체가 한글을
리터럴 '?'로 치환한 채 손상돼 있었다. 자동 복구(HTML/PDF 신뢰도 조정, `reconcile()`)가
확신을 못 가지면(T1이 아니면) **조용히 넘어가지 않고 `report_recon_candidates`에
적재 + 이 스크립트로 사람이 볼 수 있게 원문 링크·이유를 뽑는다** — 사용자 지시
"특이점이 있으면 나에게 보고해서 원문 확인할 수 있는 것도 적용" 반영.

## 무엇을 하는가
1. 대상 rcept 각각의 XML 파일에서 원문 손상 비율(`parser/xml/dart_xml_parser.py::
   _corruption_ratio`)을 잰다. 손상 아니면 스킵(이 스크립트가 처리할 대상이 아님).
2. 손상이면 `collector/pdf_lines_sync.py::recover_one()`(HTML→PDF 신뢰도 조정,
   기존 Track C 경로 재사용)으로 복구 시도.
3. 자동채택(T1) 성공분은 `store_report_lines()`로 적재.
4. 자동채택 실패(unresolved)분은 `persist_unresolved()`로 `report_recon_candidates`에
   적재하고, **이 자리에서 바로 DART 원문 링크 + 이유를 사람이 읽을 수 있게 출력**한다.

## 사용법
    python scripts/recover_and_report_corrupted_xml_2026-09-12.py --rcept 20220802000208
    python scripts/recover_and_report_corrupted_xml_2026-09-12.py --rcept-file logs/held.txt
    python scripts/recover_and_report_corrupted_xml_2026-09-12.py --report-pending
        (스캔 없이, 이미 대기열에 있는 status='new' 전부를 다시 보고만 — "지금 확인
        대기 중인 게 뭐가 있나" 확인용)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from collector.pdf_lines_sync import recover_one
from fin2.extract.reconcile_store import persist_unresolved
from fin2.extract.report_lines import store_report_lines
from fin2.extract.review_csv import DART_VIEWER
from parser.xml.dart_xml_parser import _CORRUPTION_QMARK_THRESHOLD, _corruption_ratio

SOURCE_PIPELINE = "manual_xml_corrupt"


def _read_rcept_list(path: str) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8")
    seen: dict[str, None] = {}
    for tok in raw.replace(",", "\n").split():
        tok = tok.strip()
        if tok:
            seen.setdefault(tok, None)
    return list(seen)


def _print_pending_report(session, rcepts: list[str] | None = None) -> int:
    """`report_recon_candidates`(status='new')를 사람이 읽을 보고 형태로 출력.

    rcepts 지정 시 그 목록만, 없으면 이 스크립트가 남긴(SOURCE_PIPELINE) 전체.
    반환: 출력한 rcept 수."""
    where = "status = 'new' AND source_pipeline = :sp"
    params: dict = {"sp": SOURCE_PIPELINE}
    if rcepts:
        where += " AND rcept_no = ANY(:rcepts)"
        params["rcepts"] = rcepts

    rows = session.execute(text(f"""
        SELECT rc.rcept_no, rc.corp_code, rc.basis, rc.reason,
               rc.html_confidence, rc.pdf_confidence,
               f.report_nm, f.filed_at, c.corp_name, c.market
        FROM report_recon_candidates rc
        JOIN filings f USING (rcept_no)
        JOIN corporations c ON c.corp_code = rc.corp_code
        WHERE {where}
        ORDER BY rc.rcept_no, rc.basis
    """), params).mappings().fetchall()

    if not rows:
        print("확인 대기 중인 항목이 없습니다.")
        return 0

    by_rcept: dict[str, list] = {}
    for r in rows:
        by_rcept.setdefault(r["rcept_no"], []).append(r)

    print(f"\n{'='*70}\n원문대조 확인 필요 — {len(by_rcept)}건\n{'='*70}")
    for rcept, items in by_rcept.items():
        head = items[0]
        print(f"\n  회사    {head['corp_name']} ({head['corp_code']}) {head['market']}")
        print(f"  보고서  {head['report_nm']}  r{rcept}  ({head['filed_at']})")
        print(f"  DART   {DART_VIEWER.format(rcept=rcept)}")
        for it in items:
            print(f"  [{it['basis']}] HTML={it['html_confidence']} PDF={it['pdf_confidence']} "
                  f"— {it['reason']}")
    print(f"\n{'='*70}")
    return len(by_rcept)


def _process_one(session, scraper: LegacyDartScraper, rcept: str) -> str:
    """반환: 'clean'(손상 아님, 처리 안 함) / 'recovered'(자동채택) /
    'queued'(사람 확인 대기열行) / 'error'."""
    row = session.execute(text("""
        SELECT dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
        FROM download_tasks dt JOIN filings f USING (rcept_no)
        WHERE dt.rcept_no = :r AND dt.file_type = 'xml' AND dt.status = 'completed'
    """), {"r": rcept}).mappings().first()
    if row is None or not row["file_path"] or not Path(row["file_path"]).exists():
        logger.warning(f"{rcept}: xml 파일 없음 — 스킵")
        return "error"

    ratio = _corruption_ratio(Path(row["file_path"]).read_bytes())
    if ratio <= _CORRUPTION_QMARK_THRESHOLD:
        return "clean"

    logger.info(f"{rcept}: 손상 감지(비율 {ratio:.1%}) — PDF/HTML 복구 시도")
    try:
        lines, results = recover_one(
            scraper, rcept, row["corp_code"], row["fiscal_year"], row["fiscal_period"])
    except Exception as exc:  # noqa: BLE001 — 한 건 실패가 배치 전체를 막으면 안 됨
        logger.error(f"{rcept}: 복구 시도 실패: {type(exc).__name__}: {exc}")
        return "error"

    if lines:
        n = store_report_lines(session, rcept, lines)
        logger.success(f"{rcept}: 자동복구 성공 — {n}행 적재")
        return "recovered"

    persist_unresolved(
        results, session, corp_code=row["corp_code"], rcept_no=rcept,
        report_fiscal_year=row["fiscal_year"], report_fiscal_period=row["fiscal_period"],
        source_pipeline=SOURCE_PIPELINE,
    )
    return "queued"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcept", help="쉼표구분 rcept_no")
    ap.add_argument("--rcept-file", help="줄바꿈/콤마구분 rcept_no 목록 파일")
    ap.add_argument("--report-pending", action="store_true",
                    help="스캔 없이 이미 대기열에 있는 항목만 다시 보고")
    args = ap.parse_args()

    with get_session() as session:
        if args.report_pending:
            _print_pending_report(session)
            return

        rcepts: list[str] = []
        if args.rcept:
            rcepts.extend(r.strip() for r in args.rcept.split(",") if r.strip())
        if args.rcept_file:
            rcepts.extend(_read_rcept_list(args.rcept_file))
        if not rcepts:
            ap.error("--rcept, --rcept-file, --report-pending 중 하나는 지정해야 합니다")

        counts = {"clean": 0, "recovered": 0, "queued": 0, "error": 0}
        scraper = LegacyDartScraper()
        try:
            for i, rcept in enumerate(rcepts, 1):
                outcome = _process_one(session, scraper, rcept)
                counts[outcome] += 1
                if i % 50 == 0:
                    session.commit()
                    logger.info(f"… {i}/{len(rcepts)} 처리")
            session.commit()
        finally:
            scraper.close()

        logger.success(
            f"완료 — 손상아님(스킵) {counts['clean']} · 자동복구 {counts['recovered']} · "
            f"확인대기 {counts['queued']} · 오류 {counts['error']} / 전체 {len(rcepts)}")

        if counts["queued"]:
            _print_pending_report(session, rcepts)


if __name__ == "__main__":
    main()
