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

from collector.biz_merge import merge_filings
from collector.filing_select import period_groups
from collector.models import BizMetric, BizSectionTable
from fin2.extract.biz_section import parse_biz_metrics


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
    """
    agg = {"reports": 0, "tables": 0, "metric_rows": 0, "missing_file": 0, "repeated": 0}
    for group in period_groups(session, corp_code, "annual", year=year, latest_only=latest_only):
        fy = group[0].fiscal_year
        parsed: list[tuple[str, list[dict], list[dict]]] = []
        for f in group:
            fp = Path(f.file_path)
            if not fp.exists():
                agg["missing_file"] += 1
                continue
            try:
                sec_rows, met_rows = parse_biz_metrics(fp, corp_code, f.fiscal_year)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[biz] {corp_code} {f.rcept_no} 파싱 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            # 이 보고서가 그 부분을 안 담고 있으면 그냥 건너뛴다 — 오류가 아니다(R0).
            parsed.append((f.rcept_no, sec_rows, met_rows))
            agg["reports"] += 1
        if not parsed:
            continue

        sec_all, met_merged, stats = merge_filings(parsed)
        agg["repeated"] += stats.get("repeated_identity", 0)

        # 기간 단위 재적재(멱등) — 이 연도 것을 전부 지우고 병합 결과를 다시 넣는다.
        session.execute(text(
            "DELETE FROM biz_metrics WHERE corp_code=:c AND fiscal_year=:y"),
            {"c": corp_code, "y": fy})
        session.execute(text(
            "DELETE FROM biz_section_tables WHERE corp_code=:c AND fiscal_year=:y"),
            {"c": corp_code, "y": fy})

        for s in sec_all:
            session.execute(BizSectionTable.__table__.insert().values(**s))
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
