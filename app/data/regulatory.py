"""시장조치/규제 지정 로더 — 관리종목·상장폐지·매매거래정지·불성실공시법인·회생절차. UI 비의존.

regulatory_events(collector/dart_extra.py::sync_regulatory_events 가 채움) 를 corp 단위로
집계해 '현재 활성 상태인 조치가 있는가'를 판정한다. 각 event_type 별 최신 이벤트가 지정
(is_lift=False)이면 활성, 해제(is_lift=True)면 해소로 본다. delisting/disclosure_violation 은
보수적으로 해제 판정을 하지 않는다(collector 쪽 분류 규칙과 동일 원칙).
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session

EVENT_LABELS: dict[str, str] = {
    "admin_issue":          "관리종목 지정",
    "delisting":            "상장폐지 관련",
    "trading_halt":         "매매거래정지",
    "disclosure_violation": "불성실공시법인 지정",
    "rehabilitation":       "회생절차",
    "investment_caution":   "투자주의환기종목",
}


def load_regulatory_status(corp_code: str) -> dict:
    """
    현재 활성 상태 flag 목록 + 최근 이벤트 로그.

    Returns:
        {"active": ["delisting", ...], "events": [{"filed_at","event_type","report_nm","is_lift"}, ...]}
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT filed_at, event_type, report_nm, is_lift
            FROM regulatory_events WHERE corp_code = :c
            ORDER BY filed_at DESC, id DESC
        """), {"c": corp_code}).fetchall()

    events = [{"filed_at": r[0], "event_type": r[1], "report_nm": r[2], "is_lift": r[3]} for r in rows]

    # event_type 별 최신 1건의 is_lift 로 활성 여부 판정(리스트는 filed_at DESC 정렬이라 첫 등장이 최신).
    latest_by_type: dict[str, bool] = {}
    for e in events:
        latest_by_type.setdefault(e["event_type"], e["is_lift"])

    active = [t for t, is_lift in latest_by_type.items() if not is_lift]
    return {"active": active, "events": events}


def has_active_regulatory_flag(corp_code: str) -> bool:
    """각주(주3) 트리거용 — 활성 시장조치 여부만 가볍게 확인(event_type 별 최신 1건이 미해제인지)."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT 1 FROM (
                SELECT DISTINCT ON (event_type) is_lift
                FROM regulatory_events WHERE corp_code = :c
                ORDER BY event_type, filed_at DESC, id DESC
            ) latest
            WHERE NOT is_lift
            LIMIT 1
        """), {"c": corp_code}).fetchone()
    return row is not None
