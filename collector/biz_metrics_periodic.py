"""분기·반기보고서 '사업의 내용' 부문별 사업 실적 → biz_metrics_periodic / order_backlog_periodic.

Layer 3 (R289, docs/rules/20_layer3_map.md), 사용자 결정 2026-10-28. 사업보고서용
`collector/biz_metrics.py`·`collector/order_backlog.py` 와 같은 계약(R0: 한 기간의 원본·정정본을 모두
같은 파서로 읽고 뒤 보고서가 다시 낸 항목만 덮어쓴다)이고 매핑 함수도 그대로 쓴다. 다른 점은 둘뿐이다.
 - 입력: report_type 'quarter'/'half' 필링(기간 = fiscal_year + fiscal_period), 계층2 는
   `fin2/layer2/biz_raw_tables.py` 가 R288 선택 규칙으로 쓴다(`report_type` 을 넘긴다).
 - 출력: 연간 테이블에 섞지 않고 fiscal_period 가 있는 별도 테이블. 멱등 범위 (corp, fiscal_year, fiscal_period).
원문 파일을 열지 않는다(R1) — 파일을 여는 곳은 `ensure_biz_raw_tables` 하나뿐이다.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from collector.biz_merge import merge_filings
from collector.biz_metrics import _map_row
from collector.filing_select import period_groups
from collector.models import BizMetricPeriodic, OrderBacklogPeriodic
from collector.order_backlog import _drop_out_of_range
from fin2.extract.biz_section import _narrative_unit
from fin2.extract.order_backlog import _aggregate_if_detail, map_order_table
from fin2.layer2.biz_raw_tables import ensure_biz_raw_tables

PERIODIC_TYPES = ("half", "quarter")


def _groups(session, corp_code: str, rtype: str, year: int | None, latest_only: bool,
            year_min: int | None = None):
    """period_groups of one report type. `latest_only` = every period of the most recent fiscal
    year, NOT period_groups' own latest_only: it sorts fiscal_period ascending, so with both Q1 and
    Q3 of the latest year on file it would keep Q1 and the daily run would never refresh Q3."""
    groups = period_groups(session, corp_code, rtype, year=year)
    if year_min is not None:
        groups = [g for g in groups if g[0].fiscal_year >= year_min]
    if latest_only and groups:
        groups = [g for g in groups if g[0].fiscal_year == groups[0][0].fiscal_year]
    return groups


def sync_biz_metrics_periodic_corp(session, corp_code: str, year: int | None = None,
                                   latest_only: bool = False, year_min: int | None = None) -> dict:
    """한 기업의 분기·반기보고서를 기간 단위로 파싱·병합해 biz_metrics_periodic 에 적재(멱등)."""
    agg = {"reports": 0, "tables": 0, "metric_rows": 0, "missing_file": 0}
    for rtype in PERIODIC_TYPES:
        for group in _groups(session, corp_code, rtype, year, latest_only, year_min):
            fy, fp = group[0].fiscal_year, group[0].fiscal_period
            parsed: list[tuple[str, list[dict], list[dict]]] = []
            for f in group:
                try:
                    ensure_biz_raw_tables(session, f.rcept_no, f.file_path, corp_code,
                                          f.fiscal_year, rtype)
                    db_rows = session.execute(text(
                        "SELECT table_ord, domain, metric, narrative, grid FROM biz_section_tables "
                        "WHERE rcept_no=:r AND domain IN ('production', 'sales', 'catalog') "
                        "ORDER BY table_ord"), {"r": f.rcept_no}).fetchall()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[biz-p] {corp_code} {f.rcept_no} 계층2 확보/조회 실패: "
                                   f"{type(exc).__name__}: {exc}")
                    continue
                if not db_rows:
                    agg["missing_file"] += 1
                    continue
                sec_rows, met_rows = [], []
                for r in db_rows:
                    sec_rows.append({"corp_code": corp_code, "fiscal_year": f.fiscal_year,
                                     "table_ord": r.table_ord, "metric": r.metric,
                                     "narrative": r.narrative, "grid": r.grid,
                                     "n_metric_rows": None})
                    for m in _map_row(r.domain, r.metric, r.narrative, r.grid, f.fiscal_year):
                        met_rows.append({"corp_code": corp_code, "fiscal_year": f.fiscal_year,
                                         "table_ord": r.table_ord, **m})
                parsed.append((f.rcept_no, sec_rows, met_rows))
                agg["reports"] += 1
            if not parsed:
                continue
            sec_all, met_merged, _stats = merge_filings(parsed)
            session.execute(text(
                "DELETE FROM biz_metrics_periodic "
                "WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p"),
                {"c": corp_code, "y": fy, "p": fp})
            if met_merged:
                session.execute(BizMetricPeriodic.__table__.insert(),
                                [{**m, "fiscal_period": fp} for m in met_merged])
            agg["tables"] += len(sec_all)
            agg["metric_rows"] += len(met_merged)
    return agg


def sync_order_backlog_periodic_corp(session, corp_code: str, year: int | None = None,
                                     latest_only: bool = False, year_min: int | None = None) -> dict:
    """분기·반기 수주상황 → order_backlog_periodic. 항목 동일성 = category (연간과 같다)."""
    agg = {"reports": 0, "rows": 0, "missing_file": 0, "out_of_range": 0}
    for rtype in PERIODIC_TYPES:
        for group in _groups(session, corp_code, rtype, year, latest_only, year_min):
            fy, fp = group[0].fiscal_year, group[0].fiscal_period
            merged: dict[str, dict] = {}
            parsed_any = False
            for f in group:
                try:
                    ensure_biz_raw_tables(session, f.rcept_no, f.file_path, corp_code,
                                          f.fiscal_year, rtype)
                    db_rows = session.execute(text(
                        "SELECT narrative, grid FROM biz_section_tables "
                        "WHERE rcept_no=:r AND domain='order_backlog' ORDER BY table_ord"),
                        {"r": f.rcept_no}).fetchall()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[order-p] {corp_code} {f.rcept_no} 계층2 확보/조회 실패: "
                                   f"{type(exc).__name__}: {exc}")
                    continue
                if not db_rows:
                    agg["missing_file"] += 1
                    continue
                parsed_any = True
                agg["reports"] += 1
                for db_row in db_rows:
                    default_unit = _narrative_unit(db_row.narrative or "")
                    for r in _aggregate_if_detail(map_order_table(db_row.grid, default_unit=default_unit)):
                        row = {"corp_code": corp_code, "fiscal_year": f.fiscal_year,
                               "category": r.category, "backlog_amt": r.backlog_amt,
                               "new_orders": r.new_orders, "completed": r.completed,
                               "unit": (r.unit or "")[:20] or None, "source": "html_parse",
                               "rcept_no": f.rcept_no}
                        agg["out_of_range"] += _drop_out_of_range(row)
                        merged[row.get("category") or ""] = row
            if not parsed_any:
                continue
            session.execute(text(
                "DELETE FROM order_backlog_periodic "
                "WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p"),
                {"c": corp_code, "y": fy, "p": fp})
            if merged:
                session.execute(OrderBacklogPeriodic.__table__.insert(),
                                [{**r, "fiscal_period": fp} for r in merged.values()])
            agg["rows"] += len(merged)
    return agg


def sync_biz_periodic(corps: list[str], year: int | None = None, latest_only: bool = False,
                      year_min: int | None = None) -> dict:
    """여러 기업을 기업단위 커밋·예외격리로 적재(biz_metrics_periodic + order_backlog_periodic)."""
    from collector.db import get_session

    agg = {"corps": 0, "reports": 0, "metric_rows": 0, "order_rows": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                a = sync_biz_metrics_periodic_corp(s, corp, year, latest_only, year_min)
                b = sync_order_backlog_periodic_corp(s, corp, year, latest_only, year_min)
                s.commit()
        except Exception as exc:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[biz-p] {corp} 적재 실패: {type(exc).__name__}: {exc}")
            continue
        agg["corps"] += 1
        agg["reports"] += a["reports"]
        agg["metric_rows"] += a["metric_rows"]
        agg["order_rows"] += b["rows"]
        if i % 100 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (보고서 {agg['reports']} 지표행 {agg['metric_rows']:,} "
                        f"수주행 {agg['order_rows']:,} 오류 {agg['err']})")
    return agg
