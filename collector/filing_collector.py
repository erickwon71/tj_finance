"""
공시 목록 수집기
Step 2: 기업별 DART list API → 사업/반기/분기보고서 메타데이터 → DB 저장

핵심 로직:
  - 기재정정 버전 관리: 동일 (corp_code, report_type, fiscal_year, fiscal_period) 그룹에서
    가장 최신 rcept_no를 is_final=True, 나머지는 is_final=False
  - is_final=True인 건만 download_tasks에 등록
"""
import re
from datetime import date, datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.config import COLLECT_START_DATE, REPORT_TYPE_MAP
from collector.dart_client import DartClient, DartApiError
from collector.db import get_session
from collector.models import Corporation, Filing, DownloadTask, CollectionRun


# ── 보고서명 파싱 헬퍼 ────────────────────────────────────────────────

def _detect_report_type(report_nm: str) -> Optional[str]:
    """report_nm에서 보고서 유형 식별. 해당 없으면 None."""
    for keyword, rtype in REPORT_TYPE_MAP.items():
        if keyword in report_nm:
            return rtype
    return None


def _is_amendment(report_nm: str) -> bool:
    return "[기재정정]" in report_nm or "기재정정" in report_nm


def _parse_fiscal_info(
    report_type: str,
    filed_at: date,
    report_nm: str = "",
) -> tuple[int, str]:
    """
    보고서명의 "(YYYY.MM)" 패턴 또는 접수 날짜로 회계연도·기간 결정.

    우선순위:
      1. report_nm의 "(YYYY.MM)" — DART가 명시한 결산기말 연월
         예) "사업보고서 (2023.03)" → fiscal_year=2023, FY
             "분기보고서 (2023.09)" → fiscal_year=2023, Q3
      2. filed_at 기반 추정 (폴백 — 12월 결산 기준, 비12월 오차 가능)

    기간 판별 (report_nm 기준):
      - annual  : YYYY → fiscal_year, "FY"
      - half    : YYYY → fiscal_year, "H1"
      - quarter : MM ≤ 6 → Q1 (상반기 마감), MM > 6 → Q3 (하반기 마감)

    반환: (fiscal_year: int, fiscal_period: str)
    """
    # ── 1순위: report_nm에서 (YYYY.MM) 파싱 ─────────────────────────────
    nm_match = re.search(r'\((\d{4})\.(\d{2})\)', report_nm)
    if nm_match:
        fy = int(nm_match.group(1))
        fm = int(nm_match.group(2))

        if report_type == "annual":
            return fy, "FY"
        elif report_type == "half":
            return fy, "H1"
        elif report_type == "quarter":
            # 6월 이하 마감 → Q1 (1분기), 7월 이상 마감 → Q3 (3분기)
            return fy, ("Q1" if fm <= 6 else "Q3")
        # report_type 미분류 시 폴백
        return fy, "FY"

    # ── 2순위: 접수 날짜 기반 추정 (12월 결산 가정) ───────────────────────
    y  = filed_at.year
    mo = filed_at.month

    if report_type == "annual":
        # 사업보고서: 보통 1~4월 접수 → 전년도 회계연도
        return (y - 1 if mo <= 6 else y), "FY"

    elif report_type == "half":
        # 반기보고서: 보통 7~9월 접수 → 당해 H1
        return y, "H1"

    elif report_type == "quarter":
        # Q1: 4~6월 접수, Q3: 10~12월 접수
        return y, ("Q1" if mo <= 6 else "Q3")

    return y, "FY"  # fallback


def _parse_filed_date(rcept_dt: str) -> Optional[date]:
    """'20231115' → date(2023, 11, 15)"""
    try:
        return date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
    except Exception:
        return None


# ── 버전 관리 (기재정정 처리) ─────────────────────────────────────────

def _update_is_final_flags(session, corp_code: str) -> int:
    """
    corp_code의 모든 filing을 그룹별로 최신본 1개만 is_final=True로 설정.
    반환: 변경된 행 수
    """
    from sqlalchemy import text

    # 그룹별 최신 rcept_no 찾기 (접수번호는 날짜+일련번호로 숫자 클수록 최신)
    sql = text("""
        WITH ranked AS (
            SELECT
                rcept_no,
                ROW_NUMBER() OVER (
                    PARTITION BY corp_code, report_type, fiscal_year, fiscal_period
                    ORDER BY rcept_no DESC
                ) AS rn
            FROM filings
            WHERE corp_code = :corp_code
              AND report_type IS NOT NULL
              AND fiscal_year IS NOT NULL
        )
        UPDATE filings
        SET
            is_final   = CASE WHEN r.rn = 1 THEN TRUE ELSE FALSE END,
            updated_at = NOW()
        FROM ranked r
        WHERE filings.rcept_no = r.rcept_no
          AND filings.corp_code = :corp_code
    """)
    result = session.execute(sql, {"corp_code": corp_code})
    return result.rowcount


# ── 메인 수집 함수 ────────────────────────────────────────────────────

def sync_filings(
    corp_codes: Optional[list[str]] = None,
    force: bool = False,
) -> dict:
    """
    기업별 공시 목록 수집.

    Args:
        corp_codes: 지정 시 해당 기업만 처리. None이면 DB의 모든 기업.
        force:      True면 last_filing_sync 무시하고 전체 재수집.
                    False(기본)면 last_filing_sync가 있는 기업은 건너뜀(resume).

    반환: {total_corps, processed, skipped, api_calls}
    """
    client = DartClient()
    run = CollectionRun(run_type="filing_sync", started_at=datetime.utcnow())
    stats = {"total_corps": 0, "processed": 0, "skipped": 0, "api_calls": 0}

    try:
        # ── 대상 기업 목록 로드 ───────────────────────────────
        with get_session() as session:
            q = select(Corporation).where(Corporation.is_active == True)
            if corp_codes:
                q = q.where(Corporation.corp_code.in_(corp_codes))
            # resume: 미수집 기업 우선, 수집 완료 기업은 뒤로
            if not force:
                q = q.order_by(
                    Corporation.last_filing_sync.asc().nullsfirst()
                )
            corps = session.scalars(q).all()

        stats["total_corps"] = len(corps)

        # resume 모드일 때 이미 완료된 기업 수 파악
        if not force:
            already_done = sum(1 for c in corps if c.last_filing_sync is not None)
            remaining = len(corps) - already_done
            logger.info(
                f"공시 목록 수집 시작: 전체 {len(corps):,}개 기업 "
                f"(완료 {already_done:,}개 건너뜀, 남은 {remaining:,}개)"
            )
        else:
            logger.info(f"공시 목록 수집 시작 (강제 전체): {len(corps):,}개 기업")

        today_str = datetime.today().strftime("%Y%m%d")

        # 실제 처리 대상만 미리 분리
        todo  = [c for c in corps if force or c.last_filing_sync is None]
        stats["skipped"] = len(corps) - len(todo)
        done_offset = stats["skipped"]  # 이미 완료된 기업 수 (전체 기준 offset)

        for idx, corp in enumerate(todo, 1):
            logger.info(
                f"[{done_offset + idx:>4}/{len(corps)}  남은 {idx:>4}/{len(todo)}] "
                f"{corp.corp_name} ({corp.corp_code})"
            )
            try:
                calls = _sync_one_corp(
                    client=client,
                    corp=corp,
                    bgn_de=COLLECT_START_DATE,
                    end_de=today_str,
                )
                stats["processed"] += 1
                stats["api_calls"] += calls
            except DartApiError as e:
                logger.warning(f"  DART API 오류 [{e.status}]: {e.message} — skip")
            except Exception as e:
                logger.error(f"  오류 발생: {e} — skip")

        # 실행 이력 저장
        with get_session() as session:
            run.ended_at  = datetime.utcnow()
            run.total     = stats["total_corps"]
            run.completed = stats["processed"]
            run.api_calls = stats["api_calls"]
            session.add(run)

        logger.success(
            f"공시 목록 수집 완료 — "
            f"{stats['processed']:,}/{stats['total_corps']:,}개 기업, "
            f"API {stats['api_calls']:,}콜"
        )
        return stats

    finally:
        client.close()


def _sync_one_corp(
    client: DartClient,
    corp: Corporation,
    bgn_de: str,
    end_de: str,
) -> int:
    """
    단일 기업의 공시 목록을 페이지네이션으로 전체 수집.
    반환: 소비한 API 콜 수
    """
    page_no  = 1
    api_calls = 0
    all_items: list[dict] = []

    while True:
        data = client.get_filing_list(
            corp_code=corp.corp_code,
            bgn_de=bgn_de,
            end_de=end_de,
            page_no=page_no,
            page_count=100,
        )
        api_calls += 1

        items = data.get("list", [])
        all_items.extend(items)

        total_count = int(data.get("total_count", 0))
        if len(all_items) >= total_count or not items:
            break
        page_no += 1

    # 보고서 유형 필터링
    relevant = []
    for item in all_items:
        report_nm  = item.get("report_nm", "")
        report_type = _detect_report_type(report_nm)
        if report_type is None:
            continue
        relevant.append((item, report_type))

    if not relevant:
        return api_calls

    logger.debug(f"  → 관련 공시 {len(relevant)}건 발견 (총 {len(all_items)}건 중)")

    # DB upsert
    with get_session() as session:
        rows = []
        for item, report_type in relevant:
            rcept_no  = item.get("rcept_no", "")
            report_nm = item.get("report_nm", "")
            rcept_dt  = item.get("rcept_dt", "")
            corp_cls  = item.get("corp_cls", "")

            filed_at = _parse_filed_date(rcept_dt)
            if filed_at is None:
                continue

            fiscal_year, fiscal_period = _parse_fiscal_info(report_type, filed_at, report_nm)
            amendment = _is_amendment(report_nm)

            rows.append({
                "rcept_no":      rcept_no,
                "corp_code":     corp.corp_code,
                "corp_name":     item.get("corp_name", corp.corp_name),
                "report_nm":     report_nm,
                "report_type":   report_type,
                "fiscal_year":   fiscal_year,
                "fiscal_period": fiscal_period,
                "filed_at":      filed_at,
                "corp_cls":      corp_cls,
                "is_amendment":  amendment,
                "is_final":      True,  # 임시; 아래 _update_is_final_flags에서 정정
                "updated_at":    datetime.utcnow(),
            })

        if not rows:
            return api_calls

        # DART API가 동일 rcept_no를 중복 반환하는 경우 대비 — 마지막 값 기준 유지
        seen = {}
        for row in rows:
            seen[row["rcept_no"]] = row
        rows = list(seen.values())

        # 공시 upsert (rcept_no 중복 시 메타데이터 갱신)
        stmt = pg_insert(Filing).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rcept_no"],
            set_={
                "report_nm":     stmt.excluded.report_nm,
                "is_amendment":  stmt.excluded.is_amendment,
                "updated_at":    stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)

        # 기재정정 버전 플래그 재계산
        _update_is_final_flags(session, corp.corp_code)

        # 시장 구분 갱신 (corp_cls → market)
        if rows:
            cls_map = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}
            market = cls_map.get(rows[0]["corp_cls"], None)
            if market:
                session.execute(
                    update(Corporation)
                    .where(Corporation.corp_code == corp.corp_code)
                    .values(market=market, updated_at=datetime.utcnow())
                )

        # is_final=True인 공시에 대해 download_task 생성 (없는 것만)
        final_rcept_nos = session.scalars(
            select(Filing.rcept_no).where(
                Filing.corp_code == corp.corp_code,
                Filing.is_final  == True,
            )
        ).all()

        existing_tasks = set(
            session.scalars(
                select(DownloadTask.rcept_no).where(
                    DownloadTask.rcept_no.in_(final_rcept_nos)
                )
            ).all()
        )

        new_tasks = [
            DownloadTask(rcept_no=rn, status="pending")
            for rn in final_rcept_nos
            if rn not in existing_tasks
        ]
        if new_tasks:
            session.add_all(new_tasks)
            logger.debug(f"  → 다운로드 작업 {len(new_tasks)}건 신규 등록")

        # 수집 완료 시각 기록 (resume 핵심)
        session.execute(
            update(Corporation)
            .where(Corporation.corp_code == corp.corp_code)
            .values(last_filing_sync=datetime.utcnow())
        )

    return api_calls
