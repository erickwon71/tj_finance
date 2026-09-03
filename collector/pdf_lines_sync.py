"""계층2 증분 적재 — PDF-only 복구 경로 (2026-09-03, Category C fy1999~2003 절단 복구).

배경: `docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3(2026-09-03 후속) —
fy1999~2003 필링 6,598건이 OpenDART `document.xml` API에서 결정적으로(재시도해도 동일)
잘린 XML을 받아왔다(ZIP은 CRC 통과, 서버측 원인 추정). 같은 rcept_no를 DART 웹 뷰어
(`collector/legacy_downloader.py::LegacyDartScraper`)로 재요청하면 완전한 PDF를 받을 수
있음을 표본 2건(20000329000397·20000120000003)으로 확인했다.

이 모듈은 그 PDF를 `fin2/extract/pdf.py::extract_pdf_facts()`(Track C, 기존 fact_v2용
파서 — 텍스트추출 로직은 이미 검증돼있음)로 파싱한 뒤, 그 산출물(`ExtractedFact`,
이미 canonical_account 로 매핑된 값)을 **`ReportLineRow`로 역변환**해 기존 v3 파이프라인
(`store_report_lines` → `fin2/layer3/build.py::build_corp`)에 그대로 태운다 — fact_v2를
다시 살리지 않고, PDF 텍스트추출만 재사용하는 방식.

★ `ExtractedFact.acode`는 이름과 달리 정규화된 라벨 텍스트다(`normalize_account_name(label)`,
`fin2/extract/pdf.py:225`) — report_lines의 `label_raw`로 그대로 쓴다. 계층3 `build_corp()`가
이 텍스트를 `account_mapper`로 다시 매핑하는데(report_lines 계약 그대로), 같은 매퍼로
이미 한 번 성공한 텍스트라 재매핑도 성공할 것으로 기대(검증 필요 — 이 모듈은 결과를
직접 확인하는 것까지가 책임, 재매핑 실패 시 조용히 std_v3에 안 실릴 뿐 크래시는 없음).

멱등: `store_report_lines`가 rcept 단위 delete-then-insert라 재실행 안전.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from fin2.extract.pdf import extract_pdf_facts
from fin2.extract.report_lines import ReportLineRow, store_report_lines
from fin2.extract.xbrl import ExtractedFact


def facts_to_report_lines(facts: list[ExtractedFact]) -> list[ReportLineRow]:
    """ExtractedFact(이미 canonical 매핑됨) → ReportLineRow(raw-label 계약) 역변환.

    `canonical_account`가 없는 fact(매핑 실패)는 `extract_pdf_facts()`가 이미 걸러낸다
    (fin2/extract/pdf.py:216) — 여기 도달하는 건 전부 canonical_account 보유.
    """
    out: list[ReportLineRow] = []
    for f in facts:
        if not f.canonical_account:
            continue
        statement = f.canonical_account.split(".", 1)[0].upper()
        out.append(ReportLineRow(
            corp_code=f.corp_code,
            rcept_no=f.rcept_no,
            report_fiscal_year=f.report_fiscal_year,
            report_fiscal_period=f.report_fiscal_period,
            statement=statement,
            basis=f.basis,
            label_raw=f.acode,               # 정규화된 라벨 텍스트(위 docstring 참고)
            col_index=f.col_index,
            context_fiscal_year=None,        # ★ 연도 주장 안 함(다른 추출기와 동일 관례)
            period_kind=f.period_kind,
            is_cumulative=f.is_cumulative,
            value_won=f.amount_won,
            adecimal=f.adecimal,
            unit_source="pdf",
            source_ref=f.source_ref,
            context_raw=f.acontext_raw,
        ))
    return out


def recover_one(
    scraper: LegacyDartScraper, rcept_no: str, corp_code: str,
    fiscal_year: int, fiscal_period: str,
) -> tuple[list[ReportLineRow], bytes | None, str | None]:
    """rcept_no 하나를 웹뷰어에서 재수집 → PDF면 파싱까지.

    반환: (report_lines, raw_bytes, fmt) — 실패 시 ([], None, None).
    fmt은 "pdf" 또는 "html"(HTML은 이 모듈에서 아직 파싱 안 함 — raw_bytes만 보존).
    """
    content, fmt = scraper.fetch(rcept_no)
    if not content:
        return [], None, None
    if fmt != "pdf":
        # HTML 폴백은 이 모듈의 범위 밖(모듈 docstring 참고) — 원문만 보존, 파싱은 안 함.
        return [], content, fmt

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(content)
        tmp.flush()
        facts = extract_pdf_facts(
            tmp.name, corp_code=corp_code, rcept_no=rcept_no,
            report_fiscal_year=fiscal_year, report_fiscal_period=fiscal_period,
        )
    return facts_to_report_lines(facts), content, fmt


# 대상: 2026-09-03 truncation 재검사로 확정된 fy1999~2003 절단 rcept 목록.
# `docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3 재실측 산출물
# 재현 쿼리 — CSV(세션 스크래치패드, 휘발)를 다시 못 쓸 때를 대비해 여기 SQL로 고정.
_TRUNCATED_CANDIDATES_SQL = text(
    """
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt JOIN filings f USING(rcept_no)
    WHERE dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
      AND f.corp_code = ANY(:corps)
      AND f.fiscal_year BETWEEN 1999 AND 2003
      AND NOT EXISTS (
          SELECT 1 FROM report_lines rl
          WHERE rl.corp_code = f.corp_code AND rl.report_fiscal_year = f.fiscal_year
            AND rl.report_fiscal_period = f.fiscal_period)
    ORDER BY f.fiscal_year, dt.rcept_no
    """
)


def sync_pdf_recovery(corps: list[str], limit: int | None = None) -> dict:
    """PDF 복구 경로 실행. `corps`는 Category C 시드 목록(`/tmp/backfill_c_corps_2026-09-01.txt`).

    Returns: {"candidates": n, "recovered_pdf": n, "recovered_html_only": n,
              "no_content": n, "rows": n, "errors": n}
    """
    out = {"candidates": 0, "recovered_pdf": 0, "recovered_html_only": 0,
           "no_content": 0, "rows": 0, "errors": 0}
    if not corps:
        return out

    with get_session() as session:
        targets = session.execute(
            _TRUNCATED_CANDIDATES_SQL, {"corps": list(corps)}
        ).fetchall()
    if limit:
        targets = targets[:limit]
    out["candidates"] = len(targets)
    if not targets:
        return out

    scraper = LegacyDartScraper()
    try:
        with get_session() as session:
            for i, t in enumerate(targets, 1):
                try:
                    lines, raw_bytes, fmt = recover_one(
                        scraper, t.rcept_no, t.corp_code, t.fiscal_year, t.fiscal_period)
                except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                    out["errors"] += 1
                    logger.warning(f"[pdf_recovery] {t.rcept_no} 실패: {type(exc).__name__}: {exc}")
                    continue

                if raw_bytes is None:
                    out["no_content"] += 1
                    continue
                if fmt != "pdf":
                    out["recovered_html_only"] += 1
                    continue

                out["recovered_pdf"] += 1
                if lines:
                    # report_tables 는 건너뛴다 — table_seq NOT NULL 제약(PDF 추출엔 표 순번
                    # 개념이 없음)과 충돌하고, build_corp() 은 report_tables 없이도 동작함을
                    # 검증했다(2026-09-03 표본 2건, report_lines 만으로 std_v3 정상 생성).
                    out["rows"] += store_report_lines(session, t.rcept_no, lines)

                if i % 200 == 0:
                    session.commit()
                    logger.info(f"[pdf_recovery] … {i}/{len(targets)} 처리")
            session.commit()
    finally:
        scraper.close()

    return out
