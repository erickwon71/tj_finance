"""계층2 증분 적재 — PDF-only 복구 경로 (Category C fy1999~2003 절단 복구).

배경(2026-09-03 신설): `docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3 —
fy1999~2003 필링 6,598건이 OpenDART `document.xml` API에서 결정적으로(재시도해도 동일)
잘린 XML을 받아왔다(ZIP은 CRC 통과, 서버측 원인 추정). 같은 rcept_no를 DART 웹 뷰어
(`collector/legacy_downloader.py::LegacyDartScraper`)로 재요청하면 완전한 원문을 받을 수
있음을 표본으로 확인했다.

★2026-09-07 배선 변경(사용자 지시 "파이프라인 배선부터 진행해") — `docs/plans/
html_viewer_extractor_design_2026-09-07.md` §8-8~§8-14 설계·구현 완료 후 여기 편입.
기존엔 `scraper.fetch()`(PDF 우선, HTML 폴백은 파싱 안 함)로 받은 PDF만 `extract_pdf_
facts()`로 파싱했다 — 그 결과가 fail19+missing74 93건에서 그랜드토탈이 틀리거나
빠지는 걸 실측으로 확인(원인: PDF는 좌표기반 텍스트라 표 개념이 없음). 이제
`fin2/extract/reconcile.py::reconcile()`을 호출해 basis(별도/연결)별로 HTML→PDF
신뢰도(T1/T2/T3)를 판정하고, **자동 채택된(html/pdf) basis 만** report_lines 로
싣는다 — `unresolved`(T2/T2·T3/T3, 애매함)는 report_lines 에 안 싣고 사람 확인용
`report_recon_candidates` 큐에 적재(`fin2/extract/reconcile_store.py::persist_
unresolved()`, 호출자가 담당 — 이 모듈은 여전히 DB 쓰기를 `sync_pdf_recovery()`에
위임하는 기존 구조 유지).

`facts_to_report_lines()`는 그 산출물(`ExtractedFact`, 이미 canonical_account 로
매핑된 값)을 **`ReportLineRow`로 역변환**해 기존 v3 파이프라인(`store_report_lines`
→ `fin2/layer3/build.py::build_corp`)에 그대로 태운다.

★ `ExtractedFact.acode`는 이름과 달리 정규화된 라벨 텍스트다(`normalize_account_name(label)`)
— report_lines의 `label_raw`로 그대로 쓴다. 계층3 `build_corp()`가 이 텍스트를
`account_mapper`로 다시 매핑하는데(report_lines 계약 그대로), 같은 매퍼로 이미 한 번
성공한 텍스트라 재매핑도 성공할 것으로 기대(검증 필요 — 이 모듈은 결과를 직접
확인하는 것까지가 책임, 재매핑 실패 시 조용히 std_v3에 안 실릴 뿐 크래시는 없음).

멱등: `store_report_lines`가 rcept 단위 delete-then-insert라 재실행 안전. ★단,
`lines`가 빈 리스트면(모든 basis 가 unresolved 이거나 애초에 아무것도 못 찾음)
`store_report_lines()`를 **호출하지 않는다**(`sync_pdf_recovery()`의 `if lines:`
가드) — 호출하면 delete 만 실행되고 insert 가 없어, 이전 실행에서 이미 저장돼있던
report_lines 를 아무것도 안 채우고 지워버릴 수 있다(재현·회귀 위험).
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from fin2.extract.reconcile import ReconcileResult, reconcile
from fin2.extract.reconcile_store import persist_unresolved
from fin2.extract.report_lines import ReportLineRow, store_report_lines
from fin2.extract.xbrl import ExtractedFact


def facts_to_report_lines(facts: list[ExtractedFact]) -> list[ReportLineRow]:
    """ExtractedFact(이미 canonical 매핑됨) → ReportLineRow(raw-label 계약) 역변환.

    `canonical_account`가 없는 fact(매핑 실패)는 추출기(`extract_pdf_facts()`/
    `extract_html_facts()`)가 이미 걸러낸다 — 여기 도달하는 건 전부 canonical_
    account 보유. `unit_source`는 `f.source_format`("pdf"/"html")을 그대로 써서
    이 값이 어느 경로로 복구됐는지 report_lines 에도 남긴다.
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
            unit_source=f.source_format,     # "pdf" 또는 "html"
            source_ref=f.source_ref,
            context_raw=f.acontext_raw,
        ))
    return out


def recover_one(
    scraper: LegacyDartScraper, rcept_no: str, corp_code: str,
    fiscal_year: int, fiscal_period: str,
) -> tuple[list[ReportLineRow], list[ReconcileResult]]:
    """rcept_no 하나 → HTML/PDF 신뢰도 조정(T1/T2/T3, `fin2/extract/reconcile.py`)
    거쳐 report_lines 로 변환.

    반환: (report_lines, reconcile_results). `report_lines`는 basis별
    decision 이 "html"/"pdf"(자동 채택)인 facts 만 담는다 — "unresolved"
    (T2/T2·T3/T3, 애매함)인 basis 는 안 담긴다(결측이 오염보다 낫다).
    `reconcile_results`는 호출자가 `persist_unresolved()`로 리뷰 큐에 적재하는
    데 쓴다 — 이 함수 자체는 여전히 DB 미의존(기존 관례 그대로, DB 쓰기는
    `sync_pdf_recovery()`가 담당).
    """
    results = reconcile(
        scraper, rcept_no, corp_code=corp_code,
        report_fiscal_year=fiscal_year, report_fiscal_period=fiscal_period,
    )
    facts: list[ExtractedFact] = []
    for r in results:
        if r.decision == "html":
            facts.extend(r.html_facts)
        elif r.decision == "pdf":
            facts.extend(r.pdf_facts)
        # "unresolved": 아무것도 안 실음 — 호출자가 report_recon_candidates 에 적재.
    return facts_to_report_lines(facts), results


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
    """PDF/HTML 복구 경로 실행. `corps`는 Category C 시드 목록.

    ★2026-09-07 배선 변경 — `recover_one()`이 이제 `reconcile()`(HTML→PDF
    T1/T2/T3 조정)을 쓴다. 카운터도 그에 맞춰 재정의: "recovered_pdf"/
    "recovered_html_only" 처럼 fmt 하나로 세던 옛 방식 대신, **basis별**
    decision 을 센다(별도·연결이 서로 다른 결과를 낼 수 있어서). `unresolved`
    는 `report_recon_candidates` 리뷰 큐에 적재(`persist_unresolved()`).

    Returns: {"candidates": n, "bases_html": n, "bases_pdf": n,
              "bases_unresolved": n, "rows": n, "dq_rows": n, "errors": n}
    """
    out = {"candidates": 0, "bases_html": 0, "bases_pdf": 0, "bases_unresolved": 0,
           "rows": 0, "dq_rows": 0, "errors": 0}
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
                # ★2026-09-03(밤샘 실행 중 발견) — 이 try 는 원래 recover_one() 만 감쌌다.
                # store_report_lines() 의 DB 오류(예: bigint 오버플로 — 아래 fin2/extract/
                # pdf.py 방어값 이전 데이터, 미래에도 다른 형태로 재발 가능)는 감싸지 않아서
                # 그 예외가 세션을 "실패" 상태로 만들고 스크립트 전체를 죽였다(6,592건 중
                # 2,978건만 처리하고 밤새 조용히 중단됨, 실사례). store_report_lines 까지
                # 통째로 감싸고, 실패 시 반드시 rollback 해서 다음 rcept 부터 세션을 계속
                # 쓸 수 있게 한다(한 건 실패가 전체를 막으면 안 된다는 이 코드베이스 전체
                # 관례를 여기도 지킴).
                try:
                    lines, results = recover_one(
                        scraper, t.rcept_no, t.corp_code, t.fiscal_year, t.fiscal_period)

                    for r in results:
                        if r.decision == "html":
                            out["bases_html"] += 1
                        elif r.decision == "pdf":
                            out["bases_pdf"] += 1
                        else:
                            out["bases_unresolved"] += 1

                    # ★store_report_lines()는 무조건 delete-then-insert다(rcept 단위) —
                    # lines 가 비어있는데 호출하면 delete 만 실행되고 insert 가 없어, 이전
                    # 실행에서 이미 저장돼있던 report_lines 를 아무것도 안 채우고 지워버릴
                    # 수 있다. 반드시 `if lines:` 로 가드(옛 코드도 동일 가드 유지).
                    # report_tables 는 건너뛴다 — table_seq NOT NULL 제약(PDF/HTML 추출엔
                    # 표 순번 개념이 없음)과 충돌하고, build_corp() 은 report_tables 없이도
                    # 동작함을 검증했다(2026-09-03 표본 2건, report_lines 만으로 std_v3
                    # 정상 생성).
                    if lines:
                        out["rows"] += store_report_lines(session, t.rcept_no, lines)

                    out["dq_rows"] += persist_unresolved(
                        results, session, corp_code=t.corp_code, rcept_no=t.rcept_no,
                        report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                        source_pipeline="track_c_backfill",
                    )
                except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                    out["errors"] += 1
                    session.rollback()
                    logger.warning(f"[pdf_recovery] {t.rcept_no} 실패: {type(exc).__name__}: {exc}")
                    continue

                if i % 200 == 0:
                    session.commit()
                    logger.info(f"[pdf_recovery] … {i}/{len(targets)} 처리")
            session.commit()
    finally:
        scraper.close()

    return out
