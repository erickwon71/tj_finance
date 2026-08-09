"""Layer2 writer for '사업의 내용' body tables — R1 compliance
(docs/plans/biz_content_layer2_migration_2026-08-09.md).

Detects subsection windows + expands ROWSPAN/COLSPAN grids for the 4 domains that share
`biz_section_tables` (production/sales/catalog/order_backlog), judgment-free, and returns them
ready to store. No structured mapping happens here — that is layer3's job
(collector/biz_metrics.py, collector/order_backlog.py), which reads ONLY this table's rows, never
the raw report file itself.

production/sales/catalog reuse `fin2.extract.biz_section.parse_biz_metrics` (which already
detects+maps in one pass) and keep only its raw `section_rows` half — the mapped `metric_rows`
half is discarded here and recomputed by layer3 from the stored grid. This is deliberately the
least invasive way to get a real layer2/layer3 split without touching the well-tested detection
code inside biz_section.py/sales_section.py/biz_catalog.py.

order_backlog has never had a raw-grid store before (measured 2026-08-09,
biz_content_layer2_migration_2026-08-09.md §2) — this module is what adds it, by calling
`find_order_subsections` directly and recording each window's (heading, unit) pair inside
`narrative` in the same "(단위 : X)" shape `_narrative_unit()` already knows how to parse back out
(fin2/extract/biz_section.py:486), so layer3 can recover `default_unit` from the stored row alone.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from fin2.extract.biz_section import parse_biz_metrics
from fin2.extract.order_backlog import _load_root, find_order_subsections

# Same classification the one-time migration used to backfill the 528,564 pre-existing rows
# (collector/db.py, migration "2026_08_biz_section_tables_domain") — kept here as the ongoing
# source of truth for newly-written rows. biz_section.py emits ONLY these 7 labels (verified
# 2026-08-09 via source grep, not guessed); everything else with metric != 'sales' is a
# fin2/extract/biz_catalog.py CATALOG rule label.
_PRODUCTION_METRICS = frozenset({
    "capacity", "output", "utilization",
    "capacity+output", "output+utilization", "capacity+utilization",
    "capacity+output+utilization",
})

# fin2/extract/biz_catalog.py::extract_catalog_from_root composes narrative as
# "[{subsection}] {caption_raw}[ (연속표)] :: {narrative}" — no other domain ever produces this
# shape (verified 2026-08-09: 0/141,646 production rows match, 300,000/300,000 sampled existing
# catalog rows do). This is the correction to the first cut of domain classification (Phase1
# migration "2026_08_biz_section_tables_domain"), which classified purely by `metric` and missed
# that biz_catalog.py *also* emits `metric='sales'` for its own supplementary captions
# (biz_catalog.py:266, "매출개요"/"매출유형별" 등) — 9.7%(6,148/63,167) of metric='sales' rows
# are actually catalog-origin, not sales_section.py-origin, and need `map_catalog_table` (not
# `map_sales_table`) to reconstruct correctly — see collector/db.py migration
# "2026_08_biz_section_tables_domain_sales_catalog_fix".
_CATALOG_NARRATIVE_RE = re.compile(r"^\[.*?\] .*?(?: \(연속표\))? :: ", re.S)


def _classify_domain(metric: Optional[str], narrative: Optional[str] = None) -> str:
    if narrative and _CATALOG_NARRATIVE_RE.match(narrative):
        return "catalog"
    if metric in _PRODUCTION_METRICS:
        return "production"
    if metric == "sales":
        return "sales"
    return "catalog"


def extract_biz_raw_tables(file_path: Path, corp_code: str, fiscal_year: int) -> list[dict]:
    """One filing -> rows ready for `biz_section_tables` (all 4 domains). No structured mapping.

    Row shape matches `collector.models.BizSectionTable` columns (minus rcept_no/fetched_at,
    which the caller stamps on): corp_code/fiscal_year/table_ord/domain/metric/narrative/grid/
    n_metric_rows.
    """
    section_rows, _metric_rows = parse_biz_metrics(file_path, corp_code, fiscal_year)
    out: list[dict] = [{**s, "domain": _classify_domain(s.get("metric"), s.get("narrative"))}
                       for s in section_rows]

    root = _load_root(file_path)
    if root is not None:
        start_ord = len(out)
        for i, (heading, unit, grid) in enumerate(find_order_subsections(root)):
            narrative = f"{heading} (단위 : {unit})" if unit else heading
            out.append({
                "corp_code": corp_code, "fiscal_year": fiscal_year,
                "table_ord": start_ord + i, "domain": "order_backlog",
                "metric": "order_backlog", "narrative": narrative,
                "grid": grid, "n_metric_rows": None,
            })
    return out


def store_biz_raw_tables(session, rcept_no: str, rows: list[dict]) -> int:
    """rcept_no 단위 delete-then-insert(멱등). 반환=적재 행수.

    §7-2(계획서, delete-then-insert 스코프를 (corp,fiscal_year)에서 rcept_no로 변경) 확정에
    따라 이 계층2 쓰기는 필링 단위로만 동작 — 기간 병합(R0/R2) 판단은 전혀 하지 않는다.
    """
    session.execute(text("DELETE FROM biz_section_tables WHERE rcept_no=:r"), {"r": rcept_no})
    if not rows:
        return 0
    from collector.models import BizSectionTable
    session.execute(BizSectionTable.__table__.insert(),
                     [{**r, "rcept_no": rcept_no} for r in rows])
    return len(rows)


def ensure_biz_raw_tables(session, rcept_no: str, file_path, corp_code: str, fiscal_year: int) -> bool:
    """계층3 읽기 전 온디맨드 안전장치(Phase3-3, 계획 §3.3) — 이 필링의 raw grid가 아직
    `biz_section_tables`에 없으면 지금 써넣는다. 데일리 파이프라인의 계층2 배선(Phase4)이나
    과거분 전량 백필(Phase5)이 아직 안 끝난 상태에서도 계층3 읽기가 항상 안전하도록 만든다.

    ★ 원문 파일을 여는 지점은 이 함수(경유 `extract_biz_raw_tables`)뿐이다 —
    `collector/biz_metrics.py`·`collector/order_backlog.py`는 파일을 절대 열지 않는다(R1).

    반환 = 새로 썼으면 True, 이미 있었으면(또는 파일이 없어 스킵했으면) False.
    """
    exists = session.execute(text(
        "SELECT 1 FROM biz_section_tables WHERE rcept_no=:r LIMIT 1"), {"r": rcept_no}).scalar()
    if exists:
        return False
    fp = Path(file_path)
    if not fp.exists():
        return False
    rows = extract_biz_raw_tables(fp, corp_code, fiscal_year)
    store_biz_raw_tables(session, rcept_no, rows)
    return True
