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

# PostgreSQL BIGINT 상한. 이걸 넘는 값은 실재하는 수주금액일 수 없고, 알려진 **셀 병합 결함**
# (한 셀에 여러 숫자가 이어붙음)의 산물이다. 그냥 두면 INSERT 가 통째로 터져 그 기업의
# 수주 데이터가 **전부** 사라진다(실측 2026-08-01: 00147860·00127936 두 기업이 이 경로로 실패).
# 행을 버리지 않고 **문제 필드만 NULL** 로 낮춘다 — 같은 행의 멀쩡한 값은 살린다.
_BIGINT_MAX = 9_223_372_036_854_775_807
_AMOUNT_FIELDS = ("backlog_amt", "new_orders", "completed")


def _drop_out_of_range(row: dict) -> int:
    """범위를 벗어난 금액 필드를 NULL 로 만들고, 그 개수를 돌려준다."""
    n = 0
    for f in _AMOUNT_FIELDS:
        v = row.get(f)
        if v is not None and abs(int(v)) > _BIGINT_MAX:
            row[f] = None
            n += 1
    return n


def sync_order_backlog_corp(session, corp_code: str, year: int | None = None,
                            latest_only: bool = False) -> dict:
    """한 기업의 사업보고서를 **기간 단위**로 파싱·병합해 적재(기간 단위 멱등).

    biz_metrics 와 같은 계약(docs/PARSING_RULES.md R0): 한 연도의 원본·정정본을 모두 같은
    파서로 읽고, 뒤 보고서가 다시 낸 항목만 덮어쓴다. 정정본에 없는 항목은 앞 보고서 것이 남는다.
    항목 동일성 = `category`(수주 분류) — 이 표의 유일한 차원 축.

    ★ 멱등 범위가 rcept → (corp, fiscal_year): 한 연도 결과가 여러 보고서에서 합성되므로
    rcept 단위로 지우면 다른 보고서가 넣은 같은 연도 행이 남아 **중복**된다.
    """
    from collector.filing_select import period_groups

    agg = {"reports": 0, "rows": 0, "missing_file": 0, "out_of_range": 0}
    for group in period_groups(session, corp_code, "annual", year=year, latest_only=latest_only):
        fy = group[0].fiscal_year
        merged: dict[str, dict] = {}
        parsed_any = False
        for f in group:
            fp = Path(f.file_path)
            if not fp.exists():
                agg["missing_file"] += 1
                continue
            try:
                rows = parse_order_backlog(fp, corp_code, f.fiscal_year)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[order] {corp_code} {f.rcept_no} 파싱 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            parsed_any = True
            agg["reports"] += 1
            # 이 보고서에 수주 표가 없으면 그냥 넘어간다 — 오류가 아니다(R0).
            for r in rows:
                row = {**r, "rcept_no": f.rcept_no}
                bad = _drop_out_of_range(row)
                if bad:
                    agg["out_of_range"] = agg.get("out_of_range", 0) + bad
                merged[(row.get("category") or "")] = row
        if not parsed_any:
            continue

        session.execute(text(
            "DELETE FROM order_backlog WHERE corp_code=:c AND fiscal_year=:y"),
            {"c": corp_code, "y": fy})
        if merged:
            session.execute(OrderBacklog.__table__.insert(), list(merged.values()))
        agg["rows"] += len(merged)
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
