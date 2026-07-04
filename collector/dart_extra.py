"""
DART API 추가 데이터 수집 — 임원현황, 고액보수, 수주잔고, 시장조치(규제) 이력

사용 예:
    from collector.dart_extra import sync_executives
    sync_executives("00126380", fiscal_year=2024)
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional
from loguru import logger

from collector.config import DART_API_KEY
from collector.db import get_session
from collector.models import Executive, OrderBacklog

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


def _reprt_code(fiscal_year: int) -> str:
    """사업보고서 코드 (11011). 미래 연도는 반기로 폴백."""
    return "11011"   # 사업보고서


# ── 임원 현황 ─────────────────────────────────────────────────────────────────

def fetch_executives(corp_code: str, fiscal_year: int) -> list[dict]:
    """
    DART exctvSttus API → 임원 목록 반환.
    데이터 없으면 빈 리스트.
    """
    data = _get(f"{_BASE}/exctvSttus.json", {
        "corp_code":  corp_code,
        "bsns_year":  str(fiscal_year),
        "reprt_code": _reprt_code(fiscal_year),
    })
    if not data:
        # 반기보고서로 재시도
        data = _get(f"{_BASE}/exctvSttus.json", {
            "corp_code":  corp_code,
            "bsns_year":  str(fiscal_year),
            "reprt_code": "11012",
        })
    return data.get("list", []) if data else []


def fetch_top_compensation(corp_code: str, fiscal_year: int) -> list[dict]:
    """
    DART hmvAuditIndvdlBySttus API → 5억원 이상 고액 보수 임원 반환.
    """
    data = _get(f"{_BASE}/hmvAuditIndvdlBySttus.json", {
        "corp_code":  corp_code,
        "bsns_year":  str(fiscal_year),
        "reprt_code": _reprt_code(fiscal_year),
    })
    return data.get("list", []) if data else []


def _parse_bool(s: str) -> Optional[bool]:
    if s == "Y": return True
    if s == "N": return False
    return None


def _parse_amount(s: str) -> Optional[int]:
    if not s: return None
    cleaned = re.sub(r"[^0-9]", "", s)
    return int(cleaned) if cleaned else None


def sync_executives(
    corp_code: str,
    fiscal_year: Optional[int] = None,
    years: int = 1,
) -> int:
    """
    임원 현황을 DART에서 가져와 executives 테이블에 저장.

    Args:
        corp_code:   DART 기업코드
        fiscal_year: 기준 연도 (None이면 직전 3개년)
        years:       저장할 연도 수 (fiscal_year 기준 이전 N년)

    Returns:
        저장된 행 수
    """
    if not DART_API_KEY:
        logger.error("DART_API_KEY 없음 — collector/config.py 확인")
        return 0

    from datetime import date
    base_year = fiscal_year or (date.today().year - 1)
    target_years = [base_year - i for i in range(years)]

    saved = 0
    for fy in target_years:
        rows = fetch_executives(corp_code, fy)
        if not rows:
            logger.debug(f"임원 데이터 없음: {corp_code} {fy}")
            continue

        # 고액 보수 맵 (성명 → 보수총액)
        comp_rows = fetch_top_compensation(corp_code, fy)
        comp_map: dict[str, int] = {}
        for cr in comp_rows:
            nm = cr.get("nm", "").strip()
            amt = _parse_amount(cr.get("mendng_totamt", ""))
            if nm and amt:
                comp_map[nm] = amt

        with get_session() as session:
            # 기존 데이터 삭제 후 재삽입
            from sqlalchemy import text
            session.execute(text(
                "DELETE FROM executives WHERE corp_code=:cc AND fiscal_year=:fy"
            ), {"cc": corp_code, "fy": fy})

            for r in rows:
                nm = r.get("nm", "").strip()
                if not nm or nm in ("-", ""):
                    continue
                pos = r.get("ofcps", "").strip()
                exec_obj = Executive(
                    corp_code       = corp_code,
                    fiscal_year     = fy,
                    name            = nm,
                    gender          = r.get("sexdstn", "").strip() or None,
                    birth_ym        = r.get("birth_ym", "").strip() or None,
                    position        = pos or None,
                    is_registered   = _parse_bool(r.get("rgit_exctv_at", "")),
                    is_fulltime     = _parse_bool(r.get("fte_at", "")),
                    responsibility  = r.get("chrg_bsns", "").strip() or None,
                    main_career     = r.get("main_career", "").strip()[:500] or None,
                    shareholder_rel = r.get("mxmm_shrholdr_relate", "").strip() or None,
                    tenure_period   = r.get("hffc_pd", "").strip() or None,
                    tenure_end      = r.get("tenure_end_on", "").strip() or None,
                    compensation    = comp_map.get(nm),
                    fetched_at      = datetime.utcnow(),
                )
                session.add(exec_obj)
                saved += 1

        logger.success(f"임원 저장: {corp_code} {fy} — {len(rows)}명")

    return saved


def sync_executives_all(
    fiscal_year: Optional[int] = None,
    limit: Optional[int] = None,
) -> int:
    """
    DB의 전체 상장 기업 임원 현황 일괄 수집.

    Returns:
        저장된 행 수
    """
    from sqlalchemy import text
    from datetime import date

    fy = fiscal_year or (date.today().year - 1)

    with get_session() as session:
        rows = session.execute(text(
            "SELECT corp_code FROM corporations WHERE stock_code IS NOT NULL ORDER BY corp_code"
        )).fetchall()

    corps = [r[0] for r in rows]
    if limit:
        corps = corps[:limit]

    logger.info(f"임원 수집 대상: {len(corps)}개 기업 (FY {fy})")
    total = 0
    for i, cc in enumerate(corps, 1):
        n = sync_executives(cc, fiscal_year=fy, years=1)
        total += n
        if i % 50 == 0:
            logger.info(f"  진행 {i}/{len(corps)} — 누계 {total}명")

    logger.success(f"임원 수집 완료: {total}명")
    return total


# ── 시장조치/규제 지정 이력(관리종목·상장폐지·매매정지 등) ─────────────────────
# report_nm 키워드 → (event_type, is_lift). is_lift=True 는 지정 해제/정상화. 순서대로 첫 매치 채택.
# 상장폐지는 보수적으로 해제 자동판정 안 함(법적 중대사안 — 항상 is_lift=False 로 계속 노출).
_REGULATORY_RULES: list[tuple[str, str, str, bool]] = [
    ("관리종목",         "해제", "admin_issue",          True),
    ("관리종목",         "",     "admin_issue",          False),
    ("상장폐지",         "",     "delisting",            False),
    ("매매거래정지",     "해제", "trading_halt",         True),
    ("매매거래정지",     "",     "trading_halt",         False),
    ("불성실공시법인",   "",     "disclosure_violation", False),
    ("회생절차",         "종결", "rehabilitation",       True),
    ("회생절차",         "폐지", "rehabilitation",       True),
    ("회생절차",         "",     "rehabilitation",       False),
    ("투자주의환기종목", "해제", "investment_caution",   True),
    ("투자주의환기종목", "",     "investment_caution",   False),
]


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
