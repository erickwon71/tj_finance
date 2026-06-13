"""
공시 목록 수집기
Step 2: 기업별 DART list API → 사업/반기/분기보고서 메타데이터 → DB 저장

핵심 로직:
  - 기재정정 버전 관리: 동일 (corp_code, report_type, fiscal_year, fiscal_period) 그룹에서
    가장 최신 rcept_no를 is_final=True, 나머지는 is_final=False
  - is_final=True인 건만 download_tasks에 등록
"""
import calendar
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, text, update
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


def _is_attachment_amendment(report_nm: str) -> bool:
    """첨부정정([첨부정정]): 본문은 동일하고 첨부만 정정. 재무 본문 신호로는 미발동."""
    return "[첨부정정]" in (report_nm or "")


def _detect_fiscal_month(relevant: list[tuple]) -> Optional[int]:
    """
    공시 목록에서 결산월(FYE month)을 추정.

    사업보고서(annual)의 report_nm "(YYYY.MM)" 중 MM이 결산기말 월이다.
    가장 최근(rcept_no 큰) annual 보고서를 기준으로 한다.
    annual이 없으면 None(호출부에서 기본 12 또는 기존값 유지).

    relevant: [(item_dict, report_type), ...]
    """
    annual_months: list[tuple[str, int]] = []  # (rcept_no, month)
    for item, report_type in relevant:
        if report_type != "annual":
            continue
        m = re.search(r'\((\d{4})\.(\d{2})\)', item.get("report_nm", ""))
        if m:
            annual_months.append((item.get("rcept_no", ""), int(m.group(2))))
    if not annual_months:
        return None
    # 최신 접수번호 기준 결산월
    annual_months.sort(key=lambda x: x[0], reverse=True)
    month = annual_months[0][1]
    return month if 1 <= month <= 12 else None


def compute_fiscal_year_period(
    report_type: str,
    period_end_year: int,
    period_end_month: int,
    fiscal_month: int = 12,
) -> tuple[int, str]:
    """
    보고서 기준일(period_end)과 회사 결산월(fiscal_month)로 회계연도·기간 산출.

    결산월(FYE)이 12월이 아닌 기업도 같은 회계연도의 4개 기간이 동일
    fiscal_year로 묶이도록 일반화한 산식:

      months_into = (period_end_month - fiscal_month) mod 12   # 0이면 FY 결산
      fiscal_year = year      if period_end_month <= fiscal_month
                    year + 1  otherwise          (회계연도 = 결산이 끝나는 해)

    기간은 report_type을 우선 신뢰하고, quarter만 months_into로 Q1/Q3 구분:
      - annual  → FY
      - half    → H1
      - quarter → months_into==3 → Q1, ==9 → Q3 (그 외 폴백: month≤6→Q1)

    예) 3월 결산사:
        Q1(6월말)→ FY{Y+1} Q1, H1(9월말)→ H1, Q3(12월말)→ Q3, FY(익년3월말)→ FY
        → 모두 동일 fiscal_year(=결산 해)로 그룹화.
        12월 결산사는 기존 동작과 동일.
    """
    fm = fiscal_month if fiscal_month and 1 <= fiscal_month <= 12 else 12
    months_into = (period_end_month - fm) % 12
    fiscal_year = period_end_year if period_end_month <= fm else period_end_year + 1

    if report_type == "annual":
        return fiscal_year, "FY"
    if report_type == "half":
        return fiscal_year, "H1"
    if report_type == "quarter":
        if months_into == 3:
            return fiscal_year, "Q1"
        if months_into == 9:
            return fiscal_year, "Q3"
        # 폴백: 결산월 탐지가 어긋난 경우 분기 월 기준 추정
        return fiscal_year, ("Q1" if period_end_month <= 6 else "Q3")
    return fiscal_year, "FY"


def _parse_fiscal_info(
    report_type: str,
    filed_at: date,
    report_nm: str = "",
    fiscal_month: int = 12,
) -> tuple[int, str]:
    """
    보고서명의 "(YYYY.MM)" 패턴 또는 접수 날짜로 회계연도·기간 결정.

    우선순위:
      1. report_nm의 "(YYYY.MM)" — DART가 명시한 결산기말 연월
         → compute_fiscal_year_period()로 결산월 반영 산출
      2. filed_at 기반 추정 (폴백 — 12월 결산 가정, 비12월 오차 가능)

    반환: (fiscal_year: int, fiscal_period: str)
    """
    # ── 1순위: report_nm에서 (YYYY.MM) 파싱 ─────────────────────────────
    nm_match = re.search(r'\((\d{4})\.(\d{2})\)', report_nm)
    if nm_match:
        return compute_fiscal_year_period(
            report_type,
            int(nm_match.group(1)),
            int(nm_match.group(2)),
            fiscal_month,
        )

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


# ── 결산월 변경 대응 라벨링 (PRD 01a) ──────────────────────────────────

def _period_end_from_nm(report_nm: str) -> Optional[tuple[int, int, date]]:
    """report_nm '(YYYY.MM)' → (year, month, 그 달 말일 date). 없으면 None."""
    m = re.search(r'\((\d{4})\.(\d{2})\)', report_nm or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        return None
    return (y, mo, date(y, mo, calendar.monthrange(y, mo)[1]))


def _build_fye_timeline(annual_ends: list[tuple[date, int]]) -> list[tuple[date, int]]:
    """annual 보고서들의 (기말일, 결산월)을 기말일 오름차순으로. 중복 제거."""
    return sorted(set(annual_ends), key=lambda x: x[0])


def _stub_end_dates(timeline: list[tuple[date, int]]) -> set[date]:
    """전환 stub(직전 annual 과 간격 12개월 미만) 회계연도의 기말일 집합."""
    stubs: set[date] = set()
    for i in range(1, len(timeline)):
        prev_d, cur_d = timeline[i - 1][0], timeline[i][0]
        gap = (cur_d.year - prev_d.year) * 12 + (cur_d.month - prev_d.month)
        if gap < 12:  # 단축 전환기(예 3월결산→12월결산 = 9개월)
            stubs.add(cur_d)
    return stubs


def _governing_annual(pe_date: date, timeline: list[tuple[date, int]]) -> Optional[tuple[date, int]]:
    """interim(pe_date)이 속한 회계연도를 닫는 annual = pe_date 이상 중 가장 이른 annual.
    없으면(최신 annual 이후 진행중 연도) 가장 최근 annual 로 폴백."""
    for d, mo in timeline:  # 오름차순
        if d >= pe_date:
            return (d, mo)
    return timeline[-1] if timeline else None


def relabel_corp_filings(session, corp_code: str) -> dict:
    """
    한 기업의 filings 를 '그 시점 결산월(FYE)' 기준으로 재라벨(PRD 01a).
    - period_end_date/period_end_month/fye_month_at_time/is_stub 채움.
    - fiscal_year/fiscal_period 를 time-aware FYE 로 재계산(기존 규약 유지: 회계연도=결산이 끝나는 해).
    - is_final 그룹키를 period_end_date(없으면 fy+fp) 로 재계산 → 같은 달력연도 충돌(정상연도 vs stub) 공존.
    멱등. (YYYY.MM) 없는 구형 보고서는 기존 라벨 유지·period_end NULL.
    반환: {filings, relabeled, stubs, finals}
    """
    rows = session.execute(text("""
        SELECT rcept_no, report_type, report_nm, fiscal_year, fiscal_period
        FROM filings WHERE corp_code = :c
    """), {"c": corp_code}).fetchall()

    annual_ends: list[tuple[date, int]] = []
    parsed: dict[str, dict] = {}
    for r in rows:
        pe = _period_end_from_nm(r.report_nm)
        parsed[r.rcept_no] = {
            "report_type": r.report_type, "pe": pe,
            "fy": r.fiscal_year, "fp": r.fiscal_period,
            "att": _is_attachment_amendment(r.report_nm),
        }
        if r.report_type == "annual" and pe:
            annual_ends.append((pe[2], pe[1]))

    timeline = _build_fye_timeline(annual_ends)
    stubs = _stub_end_dates(timeline)

    # 라벨 계산
    upd: list[dict] = []
    for rcept, info in parsed.items():
        rt, pe = info["report_type"], info["pe"]
        att = info["att"]
        if pe is None:
            # 구형(YYYY.MM 없음): 기존 라벨 유지
            upd.append({"rcept": rcept, "fy": info["fy"], "fp": info["fp"],
                        "ped": None, "pem": None, "fye": None, "stub": False, "att": att})
            continue
        py, pmo, pdate = pe
        if rt == "annual":
            fye, is_stub = pmo, (pdate in stubs)
        else:
            gov = _governing_annual(pdate, timeline)
            fye = gov[1] if gov else 12
            is_stub = (gov[0] in stubs) if gov else False
        fy, fp = compute_fiscal_year_period(rt, py, pmo, fye)
        upd.append({"rcept": rcept, "fy": fy, "fp": fp,
                    "ped": pdate, "pem": pmo, "fye": fye, "stub": is_stub, "att": att})

    # is_final 재그룹: (report_type, period_end_date | (fy,fp) 폴백)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for u in upd:
        rt = parsed[u["rcept"]]["report_type"]
        key = (rt, u["ped"]) if u["ped"] else (rt, "NA", u["fy"], u["fp"])
        groups[key].append(u["rcept"])
    final_set = {max(rcepts) for rcepts in groups.values()}  # 접수번호 최대=최신

    for u in upd:
        session.execute(text("""
            UPDATE filings SET
                fiscal_year=:fy, fiscal_period=:fp,
                period_end_date=:ped, period_end_month=:pem,
                fye_month_at_time=:fye, is_stub=:stub,
                is_attachment_amendment=:att,
                is_final=:isf, updated_at=NOW()
            WHERE rcept_no=:r
        """), {"fy": u["fy"], "fp": u["fp"], "ped": u["ped"], "pem": u["pem"],
               "fye": u["fye"], "stub": u["stub"], "att": u["att"],
               "isf": u["rcept"] in final_set, "r": u["rcept"]})

    return {"filings": len(upd), "stubs": len(stubs), "finals": len(final_set)}


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

    # 결산월(FYE) 추정 — annual 보고서 (YYYY.MM)에서. 없으면 기존값/기본 12.
    detected_fm = _detect_fiscal_month(relevant)
    fiscal_month = detected_fm or corp.fiscal_month or 12

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

            fiscal_year, fiscal_period = _parse_fiscal_info(
                report_type, filed_at, report_nm, fiscal_month
            )
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

        # 결산월 변경 대응 라벨링(PRD 01a): period_end/fye-at-time/is_stub/fiscal_period 재계산
        # + is_final 그룹키=period_end_date. (구 _update_is_final_flags 를 포함·대체)
        relabel_corp_filings(session, corp.corp_code)

        # 시장 구분 갱신 (corp_cls → market)
        if rows:
            cls_map = {"Y": "KOSPI", "K": "KOSDAQ"}  # N(KONEX) 제외
            market = cls_map.get(rows[0]["corp_cls"], None)
            if market:
                session.execute(
                    update(Corporation)
                    .where(Corporation.corp_code == corp.corp_code)
                    .values(market=market, updated_at=datetime.utcnow())
                )

        # download_task 생성: is_final=True + 기재정정 그룹의 원본도 포함
        from sqlalchemy import text as _text
        target_rcept_nos = [
            r[0] for r in session.execute(_text("""
                SELECT DISTINCT f.rcept_no
                FROM filings f
                WHERE f.corp_code = :corp
                  AND (
                    f.is_final = TRUE
                    OR EXISTS (
                      SELECT 1 FROM filings f2
                      WHERE f2.corp_code     = f.corp_code
                        AND f2.report_type   = f.report_type
                        AND f2.fiscal_year   = f.fiscal_year
                        AND f2.fiscal_period = f.fiscal_period
                        AND f2.is_amendment  = TRUE
                    )
                  )
            """), {"corp": corp.corp_code}).fetchall()
        ]

        existing_tasks = set(
            session.scalars(
                select(DownloadTask.rcept_no).where(
                    DownloadTask.rcept_no.in_(target_rcept_nos)
                )
            ).all()
        ) if target_rcept_nos else set()

        new_tasks = [
            DownloadTask(rcept_no=rn, status="pending")
            for rn in target_rcept_nos
            if rn not in existing_tasks
        ]
        if new_tasks:
            session.add_all(new_tasks)
            logger.debug(f"  → 다운로드 작업 {len(new_tasks)}건 신규 등록")

        # 수집 완료 시각 + 결산월 기록 (resume 핵심)
        sync_values = {"last_filing_sync": datetime.utcnow()}
        if detected_fm:
            sync_values["fiscal_month"] = detected_fm
        session.execute(
            update(Corporation)
            .where(Corporation.corp_code == corp.corp_code)
            .values(**sync_values)
        )

    return api_calls
