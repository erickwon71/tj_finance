"""B1(→B4 병합) · 수주상황 수집 — 사업보고서 본문 표 → order_backlog.

Layer3(계획 §3.2, docs/plans/biz_content_layer2_migration_2026-08-09.md) — R1 준수. 원문
XML을 직접 열지 않는다. `map_order_table`(fin2/extract/order_backlog.py)의 입력(grid+
default_unit)은 전부 `biz_section_tables`(domain='order_backlog', 계층2가 쓴다)에서 읽어
재구성한다. `ensure_biz_raw_tables`가 이 필링의 raw grid가 아직 없을 때만 온디맨드로 계층2
쓰기를 트리거하며, 원문 파일을 여는 지점은 그 함수 하나뿐이다.

usage:
    from collector.order_backlog import sync_order_backlog
    sync_order_backlog(["00126478"], latest_only=True)
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from collector.models import OrderBacklog
from fin2.extract.biz_section import _narrative_unit
from fin2.extract.order_backlog import _aggregate_if_detail, map_order_table
from fin2.layer2.biz_raw_tables import ensure_biz_raw_tables

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
    (`biz_section_tables` 는 이제 rcept 단위로 계층2가 관리 — 여기서 다시 지우지 않는다.)
    """
    from collector.filing_select import period_groups

    agg = {"reports": 0, "rows": 0, "missing_file": 0, "out_of_range": 0}
    for group in period_groups(session, corp_code, "annual", year=year, latest_only=latest_only):
        fy = group[0].fiscal_year
        merged: dict[str, dict] = {}
        parsed_any = False
        for f in group:
            try:
                ensure_biz_raw_tables(session, f.rcept_no, f.file_path, corp_code, f.fiscal_year)
                db_rows = session.execute(text(
                    "SELECT narrative, grid FROM biz_section_tables "
                    "WHERE rcept_no=:r AND domain='order_backlog' ORDER BY table_ord"),
                    {"r": f.rcept_no}).fetchall()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[order] {corp_code} {f.rcept_no} 계층2 확보/조회 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            if not db_rows:
                agg["missing_file"] += 1  # 파일 없음 또는 이 필링에 수주상황 표 자체가 없음(R0)
                continue
            rows: list[dict] = []
            for db_row in db_rows:
                default_unit = _narrative_unit(db_row.narrative or "")
                mapped = _aggregate_if_detail(map_order_table(db_row.grid, default_unit=default_unit))
                for r in mapped:
                    rows.append({
                        "corp_code": corp_code, "fiscal_year": f.fiscal_year,
                        "category": r.category, "backlog_amt": r.backlog_amt,
                        "new_orders": r.new_orders, "completed": r.completed,
                        "unit": (r.unit or "")[:20] or None, "source": "html_parse",
                    })
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
