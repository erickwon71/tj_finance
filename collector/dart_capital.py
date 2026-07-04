"""B2 · 자본이벤트 수집 — 증자/감자/CB·BW·EB 발행/자기주식 취득·처분.

DART 주요사항보고서(pblntf_ty='B') 시장전체를 report_nm 키워드로 필터링해 후보(corp_code,
rcept_no, event_type)를 찾고, 타입별 구조화 API(피지컬 field 스펙은 opendart.fss.or.kr
개발가이드 DS005 그룹으로 실제 호출해 확인함, 2026-07-04)로 상세를 채운다.

검증된 9개 엔드포인트(모두 실호출로 확인):
    paid_increase   piicDecsn    유상증자결정
    free_increase   fricDecsn    무상증자결정
    mixed_increase  pifricDecsn  유무상증자결정
    reduction       crDecsn      감자결정
    cb_issue        cvbdIsDecsn  전환사채권발행결정
    bw_issue        bdwtIsDecsn  신주인수권부사채권발행결정
    eb_issue        exbdIsDecsn  교환사채권발행결정
    treasury_acquire tsstkAqDecsn 자기주식취득결정
    treasury_dispose tsstkDpDecsn 자기주식처분결정

usage:
    from collector.dart_capital import sync_capital_events
    sync_capital_events("20260601", "20260704")
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
from loguru import logger

from collector.config import DART_API_KEY

_BASE = "https://opendart.fss.or.kr/api"


def _get(url: str, params: dict) -> Optional[dict]:
    try:
        import requests
        params = dict(params)
        params["crtfc_key"] = DART_API_KEY
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("status") == "000":
            return data
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"DART API 요청 실패: {e}")
        return None


# report_nm 매칭 규칙: (포함키워드, 제외키워드|None, event_type, endpoint). 순서대로 첫 매치 채택
# — 더 구체적인 문구(유무상증자결정)를 상위 문구(무상증자결정)보다 먼저 검사해야 오분류 방지.
_CAPITAL_RULES: list[tuple[str, Optional[str], str, str]] = [
    ("유무상증자결정",         None,       "mixed_increase",   "pifricDecsn"),
    ("무상증자결정",           None,       "free_increase",    "fricDecsn"),
    ("유상증자결정",           None,       "paid_increase",    "piicDecsn"),
    ("감자결정",               None,       "reduction",        "crDecsn"),
    ("전환사채권발행결정",     None,       "cb_issue",          "cvbdIsDecsn"),
    ("신주인수권부사채권발행결정", None,   "bw_issue",          "bdwtIsDecsn"),
    ("교환사채권발행결정",     None,       "eb_issue",          "exbdIsDecsn"),
    ("자기주식취득결정",       "신탁계약", "treasury_acquire",  "tsstkAqDecsn"),
    ("자기주식처분결정",       "신탁계약", "treasury_dispose",  "tsstkDpDecsn"),
]

# event_type → (shares 필드명(들), 부호). 필드 부재 시 shares_delta=None(정보 손실 없음 — detail JSONB 보존).
_SHARE_FIELDS: dict[str, tuple[list[str], int]] = {
    "paid_increase":    (["nstk_ostk_cnt"], 1),
    "free_increase":    (["nstk_ostk_cnt"], 1),
    "mixed_increase":   (["piic_nstk_ostk_cnt", "fric_nstk_ostk_cnt"], 1),
    "reduction":        (["crstk_ostk_cnt"], -1),
    "cb_issue":         (["cvisstk_cnt"], 1),
    "bw_issue":         (["nstk_isstk_cnt"], 1),
    "eb_issue":         (["extg_stkcnt"], 1),
    "treasury_acquire": (["aqpln_stk_ostk"], -1),   # 유통주식(float) 감소. 총발행주식수는 불변.
    "treasury_dispose": (["eaq_ostk"], 1),          # 유통주식(float) 복귀.
}

_EVENT_LABELS: dict[str, str] = {
    "paid_increase":    "유상증자결정",
    "free_increase":    "무상증자결정",
    "mixed_increase":   "유무상증자결정",
    "reduction":         "감자결정",
    "cb_issue":          "전환사채권발행결정",
    "bw_issue":          "신주인수권부사채권발행결정",
    "eb_issue":          "교환사채권발행결정",
    "treasury_acquire":  "자기주식취득결정",
    "treasury_dispose":  "자기주식처분결정",
}

# DART 상세(Decsn) API 는 접수일(rcept_dt)이 아니라 **이사회결의일(bddd) 기준**으로 bgn_de/end_de
# 필터링한다(2026-07-04 실측 확인 — 제이에스링크 CB건, 결의일 2026-05-13인데 좁은 창으론 조회 불가).
# 게다가 정정공시가 이어져도 **항상 "현재 최종상태" 1행만** 반환(과거 버전 조회 불가). 그래서:
#  - 상세조회는 넉넉한 lookback(기본 365일)으로 열어 결의일이 오래된 것도 놓치지 않는다.
#  - filed_at 은 rcept_no 앞 8자리로 파싱(상세 API 응답엔 rcept_dt 필드 자체가 없음 — DART rcept_no
#    규약이 YYYYMMDD+일련번호).
#  - 후보 스캔(list.json)은 "최근에 이 회사가 이 타입 이벤트를 냈다"를 아는 용도로만 쓰고, 상세API가
#    돌려주는 행을 그대로 전부 저장한다(개별 rcept_no 매칭 시도 안 함 — 정정 때마다 최종상태만 있어
#    매칭 자체가 성립하지 않음). 같은 결정이 정정될 때마다 새 rcept_no 로 별도 행 축적(이력 보존,
#    filings 테이블과 동일 원칙) — 논리적 중복 제거는 C9(기재정정 인식)에서 후속 처리.
_DETAIL_LOOKBACK_DAYS = 365


def classify_capital_event(report_nm: str) -> Optional[tuple[str, str]]:
    """report_nm → (event_type, endpoint), 관심 이벤트가 아니면 None."""
    for keyword, exclude, event_type, endpoint in _CAPITAL_RULES:
        if keyword in report_nm and (not exclude or exclude not in report_nm):
            return event_type, endpoint
    return None


def _parse_num(v) -> Optional[int]:
    if not v or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _shares_delta(event_type: str, detail: dict) -> Optional[int]:
    fields, sign = _SHARE_FIELDS.get(event_type, ([], 1))
    total = 0
    found = False
    for f in fields:
        n = _parse_num(detail.get(f))
        if n is not None:
            total += n
            found = True
    return sign * total if found else None


def _date_chunks(bgn_de: str, end_de: str, max_days: int = 90) -> list[tuple[str, str]]:
    start = date(int(bgn_de[:4]), int(bgn_de[4:6]), int(bgn_de[6:8]))
    end = date(int(end_de[:4]), int(end_de[4:6]), int(end_de[6:8]))
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _parse_dart_date(s: Optional[str]) -> Optional[date]:
    """'2026년 07월 03일' → date. 파싱 불가 시 None."""
    if not s or s == "-":
        return None
    import re
    m = re.match(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _find_candidates(bgn_de: str, end_de: str) -> list[dict]:
    """시장전체 주요사항보고(B) 스캔 → 관심 키워드 매칭 후보. 90일 제약은 청크 분할로 우회."""
    out = []
    for chunk_bgn, chunk_end in _date_chunks(bgn_de, end_de):
        page_no = 1
        while True:
            data = _get(f"{_BASE}/list.json", {
                "bgn_de": chunk_bgn, "end_de": chunk_end,
                "pblntf_ty": "B", "page_no": page_no, "page_count": 100,
            })
            if not data:
                break
            for item in data.get("list", []):
                report_nm = (item.get("report_nm") or "").strip()
                classified = classify_capital_event(report_nm)
                if not classified:
                    continue
                event_type, endpoint = classified
                out.append({
                    "corp_code": item.get("corp_code"),
                    "rcept_no": item.get("rcept_no"),
                    "filed_at": item.get("rcept_dt"),
                    "report_nm": report_nm,
                    "event_type": event_type,
                    "endpoint": endpoint,
                })
            total_page = data.get("total_page", 1)
            if page_no >= total_page:
                break
            page_no += 1
    return out


def fetch_capital_events(bgn_de: str, end_de: str) -> list[dict]:
    """
    후보 스캔(list.json, 이 기간에 활동한 corp+event_type 발견용) → (corp_code, endpoint) 단위
    상세조회(365일 lookback, bddd 기준) → 반환된 행 전부를 이벤트로 채택(개별 rcept_no 매칭 안 함,
    상세 API 특성상 성립 안 함 — 모듈 docstring/주석 참조).
    """
    candidates = _find_candidates(bgn_de, end_de)
    if not candidates:
        return []

    groups: dict[tuple[str, str], str] = {}
    for c in candidates:
        groups[(c["corp_code"], c["endpoint"])] = c["event_type"]

    end = date(int(end_de[:4]), int(end_de[4:6]), int(end_de[6:8]))
    detail_bgn = date(int(bgn_de[:4]), int(bgn_de[4:6]), int(bgn_de[6:8])) - timedelta(days=_DETAIL_LOOKBACK_DAYS)

    results = []
    for (corp_code, endpoint), event_type in groups.items():
        data = _get(f"{_BASE}/{endpoint}.json", {
            "corp_code": corp_code,
            "bgn_de": detail_bgn.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
        })
        for detail in (data.get("list", []) if data else []):
            rcept_no = detail.get("rcept_no")
            if not rcept_no or len(rcept_no) < 8:
                continue
            results.append({
                "corp_code": corp_code,
                "rcept_no": rcept_no,
                "filed_at": rcept_no[:8],
                "report_nm": _EVENT_LABELS.get(event_type, event_type),
                "event_type": event_type,
                "board_date": _parse_dart_date(detail.get("bddd")),
                "shares_delta": _shares_delta(event_type, detail),
                "detail": detail,
            })
    return results


def sync_capital_events(bgn_de: str, end_de: str) -> int:
    """자본이벤트를 조회해 capital_events 에 멱등 upsert(rcept_no 기준). 추적 대상만."""
    import json
    from sqlalchemy import text
    from collector.db import get_session

    events = fetch_capital_events(bgn_de, end_de)
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
                "board_date": e["board_date"],
                "report_nm": e["report_nm"][:300],
                "event_type": e["event_type"],
                "shares_delta": e["shares_delta"],
                "detail": json.dumps(e["detail"], ensure_ascii=False),
            })
        if not rows:
            return 0

        result = session.execute(text("""
            INSERT INTO capital_events
                (corp_code, rcept_no, filed_at, board_date, report_nm, event_type, shares_delta, detail)
            VALUES
                (:corp_code, :rcept_no, :filed_at, :board_date, :report_nm, :event_type, :shares_delta,
                 CAST(:detail AS JSONB))
            ON CONFLICT (rcept_no) DO NOTHING
        """), rows)
        saved = result.rowcount or 0

    if saved:
        logger.success(f"[capital] 자본이벤트 신규 {saved}건 저장 ({bgn_de}~{end_de})")
    return saved
