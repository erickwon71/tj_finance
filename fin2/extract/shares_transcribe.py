"""계층2 증분 적재 — '주식의 총수 등'(일반현황) 절 발행주식수를 `report_shares_outstanding`
으로 전사(std_v3_dq_shares_period_backfill_plan_2026-08-09.md §3.3 옵션A, Phase 2).

`collector/note_lines_sync.py::sync_layer2_lines`와 같은 대상(정기보고서 XML)을 다루지만
**별도 패스**로 둔다 — 파싱 방식이 다르다(report_lines 는 lxml tree, shares 는 raw-text
정규식 스캔, `fin2/extract/shares.py`). 원문을 다시 여는 비용은 발생하지만(파일 자체는
작음), 이미 검증된 shares.py 로직을 손대지 않고 그대로 재사용할 수 있고 두 파이프라인이
서로 독립적으로 실패격리된다.

멱등: `store_report_shares`가 rcept 단위 delete-then-insert. R0 원칙 — 섹션이 없거나
파싱 실패면 그 filing 은 그냥 건너뛴다(짐작 없음, 결측 허용).
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlalchemy import delete, insert, text

from fin2.extract.shares import extract_issued_common_shares_detailed

FY_MIN = 2015

# 대상: 이미 XML 다운로드가 끝난 정기보고서(report_lines 와 동일 소스, 계층2 관례).
_TARGETS_SQL = text(
    """
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
           f.period_end_date
    FROM download_tasks dt JOIN filings f USING(rcept_no)
    WHERE dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
      AND f.fiscal_year >= :fy_min
      AND f.corp_code = ANY(:corps)
    ORDER BY dt.rcept_no
    """
)

# 이미 적재된 rcept — corp 바운드(전역 스캔 회피, note_lines_sync.py 관례와 동일).
_LOADED_SQL = text(
    "SELECT rcept_no FROM report_shares_outstanding WHERE corp_code = ANY(:corps)"
)


def store_report_shares(session, rcept_no: str, corp_code: str, fiscal_year: int,
                        fiscal_period: str, shares_out: int, as_of_date, source_ref: str) -> int:
    """rcept_no 단위 delete-then-insert(멱등, report_lines 관례와 동일). 반환 = 적재행수(0/1)."""
    from collector.models import ReportSharesOutstanding

    session.execute(delete(ReportSharesOutstanding).where(
        ReportSharesOutstanding.rcept_no == rcept_no))
    if not shares_out:
        return 0
    session.execute(insert(ReportSharesOutstanding).values(
        rcept_no=rcept_no, corp_code=corp_code, fiscal_year=fiscal_year,
        fiscal_period=fiscal_period, shares_out=shares_out, as_of_date=as_of_date,
        source_ref=source_ref,
    ))
    return 1


def sync_shares_transcribe(corps: list[str], year_min: int = FY_MIN,
                           recheck: bool = False) -> dict:
    """주어진 기업들의 미적재 보고서에서 발행주식수를 전사한다.

    Args:
        corps: corp_code 목록
        year_min: 이 회계연도 이상만
        recheck: True 면 이미 적재된 rcept 도 다시 적재(파서 개선 소급 반영용)

    Returns: {"corps": n, "filings": n, "rows": n, "errors": n}
    """
    out = {"corps": 0, "filings": 0, "rows": 0, "errors": 0}
    if not corps:
        return out

    from collector.db import get_session
    with get_session() as session:
        targets = session.execute(
            _TARGETS_SQL, {"fy_min": year_min, "corps": list(corps)}
        ).fetchall()
        if not targets:
            return out

        if not recheck:
            loaded = {
                r[0] for r in session.execute(_LOADED_SQL, {"corps": list(corps)}).fetchall()
            }
            targets = [t for t in targets if t.rcept_no not in loaded]
        if not targets:
            return out

        seen_corps = set()
        for t in targets:
            if not Path(t.file_path).exists():
                continue
            try:
                found = extract_issued_common_shares_detailed(t.file_path)
            except Exception as exc:  # noqa: BLE001 — 개별 보고서 실패가 전체를 막으면 안 됨
                out["errors"] += 1
                logger.warning(f"[shares] {t.rcept_no} 파싱 실패: {type(exc).__name__}: {exc}")
                continue
            out["filings"] += 1
            seen_corps.add(t.corp_code)
            if not found:
                continue  # 섹션 없음/미매치 — 결측 허용(R0), 짐작 없음
            shares, label = found
            out["rows"] += store_report_shares(
                session, t.rcept_no, t.corp_code, t.fiscal_year, t.fiscal_period,
                shares, t.period_end_date, label,
            )
        session.commit()
        out["corps"] = len(seen_corps)

    return out
