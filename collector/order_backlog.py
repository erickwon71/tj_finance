"""B1(→B4 병합) · 수주상황 수집 — 사업보고서 본문 표 → order_backlog.

DART 구조화 API 가 없는 항목(사업의 내용 본문 표)이라, 로컬 저장 사업보고서 XML 을
fin2/extract/order_backlog.py 로 파싱해 order_backlog(기존 스키마, collector/models.py)
에 corp+rcept 단위 delete-then-insert(멱등). collector/biz_metrics.py 와 동일 패턴.

usage:
    from collector.order_backlog import sync_order_backlog
    sync_order_backlog(["00126478"], latest_only=True)
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import text

from collector.models import OrderBacklog
from fin2.extract.order_backlog import parse_order_backlog


def sync_order_backlog_corp(session, corp_code: str, year: int | None = None,
                            latest_only: bool = False) -> dict:
    """한 기업의 대상 사업보고서를 파싱해 order_backlog 에 적재(rcept 단위 멱등)."""
    from collector.biz_metrics import find_annual_reports  # annual 보고서 조회 재사용

    agg = {"reports": 0, "rows": 0, "missing_file": 0}
    for rcept_no, file_path, fy in find_annual_reports(session, corp_code, year, latest_only):
        fp = Path(file_path)
        if not fp.exists():
            agg["missing_file"] += 1
            continue
        try:
            rows = parse_order_backlog(fp, corp_code, fy)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[order] {corp_code} {rcept_no} 파싱 실패: {type(exc).__name__}: {exc}")
            continue

        session.execute(text("DELETE FROM order_backlog WHERE rcept_no=:r"), {"r": rcept_no})
        if rows:
            session.execute(OrderBacklog.__table__.insert(),
                            [{**r, "rcept_no": rcept_no} for r in rows])

        agg["reports"] += 1
        agg["rows"] += len(rows)
    return agg


def sync_order_backlog(corps: list[str], year: int | None = None,
                       latest_only: bool = False) -> dict:
    """여러 기업을 기업단위 커밋·예외격리로 적재. 반환=집계 카운트."""
    from collector.db import get_session

    agg = {"corps": 0, "reports": 0, "rows": 0, "missing_file": 0, "empty": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                c = sync_order_backlog_corp(s, corp, year, latest_only)
                s.commit()
        except Exception as exc:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[order] {corp} 적재 실패: {type(exc).__name__}: {exc}")
            continue
        agg["corps"] += 1
        for k in ("reports", "rows", "missing_file"):
            agg[k] += c[k]
        if c["rows"] == 0:
            agg["empty"] += 1
        if i % 100 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (보고서 {agg['reports']} "
                        f"행 {agg['rows']:,} 빈 {agg['empty']} 오류 {agg['err']})")
    return agg
