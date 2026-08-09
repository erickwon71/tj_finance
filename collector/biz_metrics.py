"""B4 · 생산능력/생산실적/가동률 수집 — 사업보고서 본문 표에서 구조화 지표 적재.

Layer3(계획 §3.2, docs/plans/biz_content_layer2_migration_2026-08-09.md) — R1 준수. 원문
XML을 직접 열지 않는다. 구조화 매핑(`map_biz_table`/`map_sales_table`/`map_catalog_table`)의
입력(BizTable/SalesTable/CaptionedTable)은 전부 `biz_section_tables`(계층2,
`fin2/layer2/biz_raw_tables.py`가 쓴다)에서 읽어 재구성한다. `ensure_biz_raw_tables`가 이
필링의 raw grid가 아직 없을 때만 온디맨드로 계층2 쓰기를 트리거하는데, 원문 파일을 여는
지점은 그 함수(경유 `extract_biz_raw_tables`) 하나뿐이다.

수집기(scripts/collect_biz_metrics.py)와 파이프라인(scripts/collect_new.py)이 공유.
사업의 내용 절은 사업보고서(annual)에만 있으므로 report_type='annual' 만 대상.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger
from sqlalchemy import text

from collector.biz_merge import merge_filings
from collector.filing_select import period_groups
from collector.models import BizMetric
from fin2.extract.biz_catalog import CaptionedTable, map_catalog_table
from fin2.extract.biz_section import BizTable, map_biz_table
from fin2.extract.sales_section import SalesTable, map_sales_table
from fin2.layer2.biz_raw_tables import ensure_biz_raw_tables

# fin2/extract/biz_catalog.py::extract_catalog_from_root 가 biz_section_tables.narrative 에
# 저장하는 합성 포맷(subsection/caption_raw/inherited/narrative 를 한 TEXT 컬럼에 눌러 담음) —
# 계층3가 CaptionedTable 을 재구성하려면 이걸 역파싱해야 한다. 비탐욕 매칭이라 " :: " 첫 등장에서
# 끊기므로, 원본 f-string 이 만든 구조(캡션은 짧고 " :: " 는 정확히 한 번만 삽입)와 정확히 대응.
_CATALOG_NARRATIVE_RE = re.compile(
    r"^\[(?P<subsection>.*?)\] (?P<caption_raw>.*?)(?P<inherited> \(연속표\))? :: (?P<narrative>.*)$",
    re.S)


def _clip(v: Optional[str], n: int) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v[:n] if v else None


def _map_row(domain: str, metric: Optional[str], narrative: Optional[str],
            grid: list, fiscal_year: int) -> list[dict]:
    """biz_section_tables 한 행(도메인 무관 공용 컬럼) -> 구조화 biz_metrics 행 리스트.

    각 도메인의 dataclass(BizTable/SalesTable/CaptionedTable)를 저장된 컬럼만으로 재구성해
    기존 검증된 매핑 함수(map_biz_table/map_sales_table/map_catalog_table)를 그대로 호출한다
    — 매핑 로직 자체는 무변경(계획 §2 확인: 이미 순수 데이터 함수).
    """
    if domain == "production":
        bt = BizTable(metric=metric or "", narrative=narrative or "", grid=grid)
        return [{
            "metric": _clip(r.metric, 20), "channel": None,
            "segment": _clip(r.segment, 120), "item": _clip(r.item, 150),
            "period_label": _clip(r.period_label, 60), "period_year": r.period_year,
            "value": r.value, "unit": _clip(r.unit, 30), "is_ratio": r.is_ratio,
        } for r in map_biz_table(bt, fiscal_year)]

    if domain == "sales":
        st = SalesTable(narrative=narrative or "", grid=grid)
        return [{
            "metric": "sales", "channel": _clip(r.channel, 12),
            "segment": _clip(r.segment, 120), "item": _clip(r.item, 150),
            "period_label": _clip(r.period_label, 60), "period_year": r.period_year,
            "value": r.value, "unit": _clip(r.unit, 30), "is_ratio": False,
        } for r in map_sales_table(st, fiscal_year)]

    if domain == "catalog":
        m = _CATALOG_NARRATIVE_RE.match(narrative or "")
        if m:
            subsection = m.group("subsection")
            caption_raw = m.group("caption_raw")
            inherited = bool(m.group("inherited"))
            inner_narrative = m.group("narrative")
        else:  # 저장 당시 포맷이 없던(방어적) 예외 케이스 — 통짜 narrative 로 폴백.
            subsection, caption_raw, inherited, inner_narrative = "", "", False, narrative or ""
        ct = CaptionedTable(subsection=subsection, caption="", caption_raw=caption_raw,
                            narrative=inner_narrative, grid=grid, inherited=inherited)
        return [{
            "metric": _clip(r.metric, 20), "channel": None,
            "segment": _clip(r.segment, 120), "item": _clip(r.item, 150),
            "period_label": _clip(r.period_label, 60), "period_year": r.period_year,
            "value": r.value, "unit": _clip(r.unit, 30), "is_ratio": r.is_ratio,
        } for r in map_catalog_table(ct, metric or "", fiscal_year)]

    raise ValueError(f"unknown biz_section_tables.domain: {domain!r}")


def find_annual_reports(session, corp_code: str, year: int | None = None,
                        latest_only: bool = False) -> list[tuple[str, str, int]]:
    """(rcept_no, file_path, fiscal_year) — 한 기간의 **모든** 보고서를 오래된 것부터.

    ★ `is_final` 로 거르지 않는다(docs/PARSING_RULES.md R0/R2-0). `is_final` 은 "그룹에서
    가장 나중 접수" 표지일 뿐 내용 완전성과 무관하고, 본문을 하나도 담지 않는 `[첨부정정]`
    이 그 표지를 가져간다(실측: 본문 포함률 0%, 260건 조사). 이걸로 필터링하던 종전 구현이
    **본문이 있는 판을 통째로 배제**해 547건(447개사)을 미적재로 만들었다.

    호출측은 반환된 보고서를 **모두 같은 파서로** 읽고, 뒤 보고서가 다시 낸 항목만 덮어쓰면
    된다(collector/biz_merge.py). 정정본이 일부만 담고 있어도 나머지는 앞 보고서 것이 남는다.
    """
    groups = period_groups(session, corp_code, "annual", year=year, latest_only=latest_only)
    return [(f.rcept_no, f.file_path, f.fiscal_year) for g in groups for f in g]


def sync_biz_metrics_corp(session, corp_code: str, year: int | None = None,
                          latest_only: bool = False) -> dict:
    """한 기업의 사업보고서를 **기간 단위**로 파싱·병합해 적재(기간 단위 멱등). 반환=카운트.

    ★ 기간(연도) 안의 원본·정정본을 **모두 같은 파서로** 읽고 시간순으로 항목을 덮어쓴다
    (docs/PARSING_RULES.md R0). 정정본에 없는 항목은 앞 보고서 것이 그대로 남는다.

    멱등 범위가 rcept → **(corp, fiscal_year)** 로 바뀐 이유: 한 연도의 결과가 여러 보고서에서
    합성되므로, rcept 단위로 지우면 다른 보고서가 넣어 둔 같은 연도 행이 남아 중복된다.
    (`biz_section_tables` 는 이제 rcept 단위로 계층2가 관리 — 여기서 다시 지우지 않는다.)
    """
    agg = {"reports": 0, "tables": 0, "metric_rows": 0, "missing_file": 0, "repeated": 0}
    for group in period_groups(session, corp_code, "annual", year=year, latest_only=latest_only):
        fy = group[0].fiscal_year
        parsed: list[tuple[str, list[dict], list[dict]]] = []
        for f in group:
            try:
                ensure_biz_raw_tables(session, f.rcept_no, f.file_path, corp_code, f.fiscal_year)
                db_rows = session.execute(text(
                    "SELECT table_ord, domain, metric, narrative, grid FROM biz_section_tables "
                    "WHERE rcept_no=:r AND domain IN ('production', 'sales', 'catalog') "
                    "ORDER BY table_ord"), {"r": f.rcept_no}).fetchall()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[biz] {corp_code} {f.rcept_no} 계층2 확보/조회 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            if not db_rows:
                agg["missing_file"] += 1  # 파일 없음 또는 이 필링에 사업의 내용 본문표 자체가 없음(R0)
                continue
            sec_rows: list[dict] = []
            met_rows: list[dict] = []
            for r in db_rows:
                sec_rows.append({
                    "corp_code": corp_code, "fiscal_year": f.fiscal_year,
                    "table_ord": r.table_ord, "metric": r.metric,
                    "narrative": r.narrative, "grid": r.grid, "n_metric_rows": None,
                })
                for m in _map_row(r.domain, r.metric, r.narrative, r.grid, f.fiscal_year):
                    met_rows.append({
                        "corp_code": corp_code, "fiscal_year": f.fiscal_year,
                        "table_ord": r.table_ord, **m,
                    })
            # 이 보고서가 그 부분을 안 담고 있으면 그냥 건너뛴다 — 오류가 아니다(R0).
            parsed.append((f.rcept_no, sec_rows, met_rows))
            agg["reports"] += 1
        if not parsed:
            continue

        sec_all, met_merged, stats = merge_filings(parsed)
        agg["repeated"] += stats.get("repeated_identity", 0)

        # 기간 단위 재적재(멱등) — biz_metrics 만. biz_section_tables 는 계층2(rcept 단위)가 관리.
        session.execute(text(
            "DELETE FROM biz_metrics WHERE corp_code=:c AND fiscal_year=:y"),
            {"c": corp_code, "y": fy})

        if met_merged:
            session.execute(BizMetric.__table__.insert(), met_merged)

        agg["tables"] += len(sec_all)
        agg["metric_rows"] += len(met_merged)
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
