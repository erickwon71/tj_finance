"""
DART API 추가 데이터 수집 — 시장조치(규제) 이력(regulatory_events).

시장조치 공시는 정기보고서가 아니어서 로컬 원문으로 만들 수 없다 — 사용자 승인 API 예외
(docs/plans/api_to_document_migration_plan_2026-10-05.md §7). 임원현황·고액보수 API 수집은
2026-10-05 원문 '임원 및 직원 등의 현황'·'임원의 보수 등' 표로 대체돼 삭제했다
(collector/doc_sections_sync.py).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from loguru import logger

from collector.config import DART_API_KEY
from collector.db import get_session

_BASE = "https://opendart.fss.or.kr/api"


def _get(url: str, params: dict) -> Optional[dict]:
    """DART API GET 요청."""
    try:
        import requests
        params["crtfc_key"] = DART_API_KEY
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("status") == "000":
            return data
        logger.debug(f"DART API 오류 [{data.get('status')}]: {data.get('message')}")
        return None
    except Exception as e:
        logger.debug(f"DART API 요청 실패: {e}")
        return None


# ── 시장조치(규제) 이력 ───────────────────────────────────────────────────────

def classify_regulatory_event(report_nm: str) -> Optional[tuple[str, bool]]:
    """report_nm → (event_type, is_lift), 관심 이벤트가 아니면 None."""
    for keyword, sub_keyword, event_type, is_lift in _REGULATORY_RULES:
        if keyword in report_nm and (not sub_keyword or sub_keyword in report_nm):
            return event_type, is_lift
    return None


def _date_chunks(bgn_de: str, end_de: str, max_days: int = 90) -> list[tuple[str, str]]:
    """corp_code 없는 list.json 조회는 최대 90일 창만 허용 — 긴 구간을 청크로 분할."""
    from datetime import timedelta as _td
    start = date(int(bgn_de[:4]), int(bgn_de[4:6]), int(bgn_de[6:8]))
    end = date(int(end_de[:4]), int(end_de[4:6]), int(end_de[6:8]))
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + _td(days=max_days - 1), end)
        chunks.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + _td(days=1)
    return chunks


def _fetch_regulatory_events_chunk(bgn_de: str, end_de: str) -> list[dict]:
    """단일 청크(<=90일) 조회. 페이지네이션 처리."""
    out: list[dict] = []
    page_no = 1
    page_count = 100
    while True:
        data = _get(f"{_BASE}/list.json", {
            "bgn_de": bgn_de, "end_de": end_de,
            "pblntf_ty": "I", "page_no": page_no, "page_count": page_count,
        })
        if not data:
            break
        for item in data.get("list", []):
            report_nm = (item.get("report_nm") or "").strip()
            classified = classify_regulatory_event(report_nm)
            if not classified:
                continue
            event_type, is_lift = classified
            out.append({
                "corp_code": item.get("corp_code"),
                "rcept_no": item.get("rcept_no"),
                "filed_at": item.get("rcept_dt"),
                "report_nm": report_nm,
                "event_type": event_type,
                "is_lift": is_lift,
            })
        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break
        page_no += 1
    return out


def fetch_regulatory_events(bgn_de: str, end_de: str) -> list[dict]:
    """
    DART 거래소공시(pblntf_ty=I) 시장전체 조회(corp_code 생략) → 관심 이벤트만 필터링.
    bgn_de/end_de = "YYYYMMDD". corp_code 미지정 조회는 DART 제약상 최대 90일 창만
    허용되므로 내부적으로 청크 분할(백필 등 긴 구간도 안전).
    """
    out: list[dict] = []
    for chunk_bgn, chunk_end in _date_chunks(bgn_de, end_de):
        out.extend(_fetch_regulatory_events_chunk(chunk_bgn, chunk_end))
    return out


def sync_regulatory_events(bgn_de: str, end_de: str) -> int:
    """
    시장조치 이벤트를 조회해 regulatory_events 에 멱등 upsert(rcept_no 기준).
    추적 대상(종목코드 있는 상장기업)이 아닌 corp_code 는 skip.

    Returns:
        신규 저장된 행 수
    """
    from sqlalchemy import text

    events = fetch_regulatory_events(bgn_de, end_de)
    if not events:
        return 0

    with get_session() as session:
        tracked = {r[0] for r in session.execute(text(
            "SELECT corp_code FROM corporations WHERE stock_code IS NOT NULL"
        )).fetchall()}

        rows = []
        for e in events:
            if e["corp_code"] not in tracked or not e["filed_at"]:
                continue
            rows.append({
                "corp_code": e["corp_code"],
                "rcept_no": e["rcept_no"],
                "filed_at": date(int(e["filed_at"][:4]), int(e["filed_at"][4:6]), int(e["filed_at"][6:8])),
                "report_nm": e["report_nm"][:300],
                "event_type": e["event_type"],
                "is_lift": e["is_lift"],
            })
        if not rows:
            return 0

        result = session.execute(text("""
            INSERT INTO regulatory_events (corp_code, rcept_no, filed_at, report_nm, event_type, is_lift)
            VALUES (:corp_code, :rcept_no, :filed_at, :report_nm, :event_type, :is_lift)
            ON CONFLICT (rcept_no) DO NOTHING
        """), rows)
        saved = result.rowcount or 0

    if saved:
        logger.success(f"[regulatory] 시장조치 이벤트 신규 {saved}건 저장 ({bgn_de}~{end_de})")
    return saved
