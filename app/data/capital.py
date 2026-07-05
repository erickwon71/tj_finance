"""자본이벤트 로더 — 증자/감자/CB·BW·EB 발행/자기주식. UI 비의존.

capital_events(collector/dart_capital.py::sync_capital_events 가 채움)를 소비해 B-2
발행주식수 차트의 dilution 오버레이 + "잠재 희석 %" 지표를 만든다.

주의(정확성 한계, 2026-07-04 설계 결정):
- CB/BW/EB 는 "잠재" 주식수(전환/행사 시 발행될 수 있는 최대치)로, 이미 전환·상환·취소된
  건도 구분 없이 합산한다(상태 추적 미구현) — 상한선(upper bound) 추정치로만 사용.
- 자기주식 취득/처분은 총발행주식수를 바꾸지 않음(유통주식만 영향) — "잠재 희석 %" 계산에서 제외.
- 같은 결정이 정정될 때마다 새 rcept_no 로 별도 행이 쌓이므로(이력 보존), 단순 합산 시 정정 이력이
  중복 집계될 수 있다(C9 기재정정 인식 이전까지 알려진 한계).
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session

EVENT_LABELS: dict[str, str] = {
    "paid_increase":     "유상증자",
    "free_increase":     "무상증자",
    "mixed_increase":    "유무상증자",
    "reduction":         "감자",
    "cb_issue":          "전환사채(CB)",
    "bw_issue":          "신주인수권부사채(BW)",
    "eb_issue":          "교환사채(EB)",
    "treasury_acquire":  "자기주식 취득",
    "treasury_dispose":  "자기주식 처분",
}

# 총발행주식수에 즉시/확정 영향(증가 +, 감소 -). 자기주식은 유통주식만 영향이라 제외.
_ISSUED_SHARE_TYPES = {"paid_increase", "free_increase", "mixed_increase", "reduction"}
# 전환/행사 시 잠재적으로 신주가 될 수 있는 사채류(미전환 가정 상한선 추정).
_POTENTIAL_DILUTION_TYPES = {"cb_issue", "bw_issue", "eb_issue"}

# 타임라인 시각 분류: 확정증가/확정감소/잠재/자기주식(총주식수 불변).
_EVENT_CATEGORY: dict[str, str] = {
    "paid_increase": "confirmed_up", "free_increase": "confirmed_up",
    "mixed_increase": "confirmed_up", "reduction": "confirmed_down",
    "cb_issue": "potential", "bw_issue": "potential", "eb_issue": "potential",
    "treasury_acquire": "treasury", "treasury_dispose": "treasury",
}


def load_capital_events(corp_code: str) -> list[dict]:
    """corp 의 전체 자본이벤트 이력(최신순)."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT filed_at, board_date, event_type, shares_delta, rcept_no
            FROM capital_events WHERE corp_code = :c
            ORDER BY filed_at DESC, id DESC
        """), {"c": corp_code}).fetchall()
    return [{"filed_at": r[0], "board_date": r[1], "event_type": r[2],
              "shares_delta": r[3], "rcept_no": r[4]} for r in rows]


def yearly_dilution_overlay(events: list[dict]) -> dict[int, dict]:
    """연도별 {issued_delta, potential_delta, n} 집계 — 차트 오버레이용."""
    by_year: dict[int, dict] = {}
    for e in events:
        d = e["board_date"] or e["filed_at"]
        if not d:
            continue
        yr = by_year.setdefault(d.year, {"issued_delta": 0, "potential_delta": 0, "n": 0, "types": set()})
        yr["n"] += 1
        yr["types"].add(e["event_type"])
        sd = e.get("shares_delta")
        if sd is None:
            continue
        if e["event_type"] in _ISSUED_SHARE_TYPES:
            yr["issued_delta"] += sd
        elif e["event_type"] in _POTENTIAL_DILUTION_TYPES:
            yr["potential_delta"] += sd
    return by_year


def dilution_timeline(events: list[dict]) -> list[dict]:
    """자본이벤트를 날짜 오름차순 타임라인으로. 확정 발행주식 누적증감(cum_confirmed) 포함.

    각 항목: {date, event_type, label, category, shares_delta, cum_confirmed}.
    date = board_date 우선, 없으면 filed_at. 누적은 확정증감(증자/감자)만 반영(잠재·자기주식 제외)."""
    items = []
    for e in events:
        d = e.get("board_date") or e.get("filed_at")
        if not d:
            continue
        items.append({
            "date": d, "event_type": e["event_type"],
            "label": EVENT_LABELS.get(e["event_type"], e["event_type"]),
            "category": _EVENT_CATEGORY.get(e["event_type"], "other"),
            "shares_delta": e.get("shares_delta"),
        })
    items.sort(key=lambda x: x["date"])
    cum = 0
    for it in items:
        if it["category"] in ("confirmed_up", "confirmed_down") and it["shares_delta"] is not None:
            cum += it["shares_delta"]
        it["cum_confirmed"] = cum
    return items


def potential_dilution_pct(events: list[dict], current_shares_out: int, years: int = 3) -> float | None:
    """최근 N년 CB/BW/EB 잠재발행주식 합 / 현재 발행주식수 (%). 상한선 추정 — 전환/상환 상태 미반영."""
    if not current_shares_out:
        return None
    from datetime import date
    cutoff = date(date.today().year - years, 1, 1)
    total = 0
    found = False
    for e in events:
        if e["event_type"] not in _POTENTIAL_DILUTION_TYPES:
            continue
        d = e["board_date"] or e["filed_at"]
        if not d or d < cutoff or e.get("shares_delta") is None:
            continue
        total += e["shares_delta"]
        found = True
    return (total / current_shares_out * 100) if found else None
