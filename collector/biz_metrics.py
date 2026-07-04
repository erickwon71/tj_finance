"""B4 · 생산능력/생산실적/가동률 수집 — 사업보고서 본문 표에서 구조화 지표 적재.

DART 구조화 API 가 없는 항목(사업의 내용 본문 표)이라, 로컬 저장 사업보고서 XML 을
fin2/extract/biz_section.py 로 파싱해 biz_section_tables(원본 grid, 무손실) +
biz_metrics(구조화 long-format) 두 테이블에 corp+rcept 단위 delete-then-insert(멱등).

수집기(scripts/collect_biz_metrics.py)와 파이프라인(scripts/collect_new.py)이 공유.
사업의 내용 절은 사업보고서(annual)에만 있으므로 report_type='annual' 만 대상.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import text

from collector.models import BizMetric, BizSectionTable
from fin2.extract.biz_section import parse_biz_metrics


def find_annual_reports(session, corp_code: str, year: int | None = None,
                        latest_only: bool = False) -> list[tuple[str, str, int]]:
    """(rcept_no, file_path, fiscal_year) 목록. year 지정 시 그 연도만, latest_only 면 최신 1건."""
    sql = """
        SELECT dt.rcept_no, dt.file_path, f.fiscal_year
        FROM download_tasks dt
        JOIN filings f ON f.rcept_no = dt.rcept_no
        WHERE f.corp_code = :c
          AND f.report_type = 'annual'
          AND f.is_final = TRUE
          AND dt.status = 'completed'
          AND dt.file_type = 'xml'
          AND dt.file_path IS NOT NULL
    """
    params: dict = {"c": corp_code}
    if year is not None:
        sql += " AND f.fiscal_year = :y"
        params["y"] = year
    sql += " ORDER BY f.fiscal_year DESC, dt.rcept_no DESC"
    if latest_only:
        sql += " LIMIT 1"
    return [(r.rcept_no, r.file_path, r.fiscal_year)
            for r in session.execute(text(sql), params).fetchall()]


def sync_biz_metrics_corp(session, corp_code: str, year: int | None = None,
                          latest_only: bool = False) -> dict:
    """한 기업의 대상 사업보고서를 파싱해 두 테이블에 적재(rcept 단위 멱등). 반환=카운트."""
    agg = {"reports": 0, "tables": 0, "metric_rows": 0, "missing_file": 0}
    for rcept_no, file_path, fy in find_annual_reports(session, corp_code, year, latest_only):
        fp = Path(file_path)
        if not fp.exists():
            agg["missing_file"] += 1
            continue
        try:
            sec_rows, met_rows = parse_biz_metrics(fp, corp_code, fy)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[biz] {corp_code} {rcept_no} 파싱 실패: {type(exc).__name__}: {exc}")
            continue

        # rcept 단위 재적재(멱등) — 표가 0개여도 이전 잔재를 지운다.
        session.execute(text("DELETE FROM biz_metrics WHERE rcept_no=:r"), {"r": rcept_no})
        session.execute(text("DELETE FROM biz_section_tables WHERE rcept_no=:r"), {"r": rcept_no})

        for s in sec_rows:
            session.execute(BizSectionTable.__table__.insert().values(rcept_no=rcept_no, **s))
        if met_rows:
            session.execute(BizMetric.__table__.insert(),
                            [{**m, "rcept_no": rcept_no} for m in met_rows])

        agg["reports"] += 1
        agg["tables"] += len(sec_rows)
        agg["metric_rows"] += len(met_rows)
    return agg


def sync_biz_metrics(corps: list[str], year: int | None = None,
                     latest_only: bool = False) -> dict:
    """여러 기업을 기업단위 커밋·예외격리로 적재. 반환=집계 카운트."""
    from collector.db import get_session

    agg = {"corps": 0, "reports": 0, "tables": 0, "metric_rows": 0,
           "missing_file": 0, "empty": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                c = sync_biz_metrics_corp(s, corp, year, latest_only)
                s.commit()
        except Exception as exc:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[biz] {corp} 적재 실패: {type(exc).__name__}: {exc}")
            continue
        agg["corps"] += 1
        for k in ("reports", "tables", "metric_rows", "missing_file"):
            agg[k] += c[k]
        if c["metric_rows"] == 0:
            agg["empty"] += 1
        if i % 100 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (보고서 {agg['reports']} "
                        f"표 {agg['tables']} 지표행 {agg['metric_rows']:,} "
                        f"빈 {agg['empty']} 오류 {agg['err']})")
    return agg
