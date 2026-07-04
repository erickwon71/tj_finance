"""사업지표(생산능력/생산실적/가동률) 로더 — B4. UI 비의존.

biz_metrics(collector/biz_metrics.py::sync_biz_metrics 가 채움, 사업보고서 본문표에서
파싱)를 소비. 한 corp 는 여러 사업연도 보고서를 가질 수 있고, 각 보고서가 3개년 비교치를
담으므로 (metric, segment, item, period_year, period_label) 단위로 **가장 최근 보고서**의
값을 채택(DISTINCT ON)해 중복을 제거한 시계열을 만든다.

주의(정확성 한계, 2026-07-04):
- 부문/품목마다 단위가 다르다(천대·천배럴·천톤·EA…) → 여러 항목을 한 차트에 섞으면 오해.
  가동률(%)만 공통이라 함께 그리고, 생산능력/생산실적은 단위별 표로 보여준다.
- period_year 가 NULL 인 행(표준생산능력·가동가능일수 같은 비시계열 보조표)은 별도 취급.
"""
from __future__ import annotations

from sqlalchemy import text

from collector.db import get_session

METRIC_LABELS = {"capacity": "생산능력", "output": "생산실적", "utilization": "가동률"}


def load_biz_production(corp_code: str) -> dict:
    """corp 의 사업지표 시계열. 반환: {available, report_year, years, rows}."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (metric, segment, item, period_year, period_label)
                   metric, segment, item, period_year, period_label,
                   value, unit, is_ratio, fiscal_year
            FROM biz_metrics
            WHERE corp_code = :c
            ORDER BY metric, segment, item, period_year, period_label,
                     fiscal_year DESC, rcept_no DESC
        """), {"c": corp_code}).fetchall()
    recs = [dict(r._mapping) for r in rows]
    if not recs:
        return {"available": False}
    return {
        "available": True,
        "report_year": max(r["fiscal_year"] for r in recs),
        "years": sorted({r["period_year"] for r in recs if r["period_year"] is not None}),
        "rows": recs,
    }


def _seg_label(r: dict) -> str:
    """부문·품목을 하나의 표시 라벨로."""
    seg, item = (r.get("segment") or "").strip(), (r.get("item") or "").strip()
    if seg and item and seg != item:
        return f"{seg} · {item}"
    return seg or item or "—"


def utilization_series(rows: list[dict]) -> list[tuple[str, list[tuple[int, float]]]]:
    """가동률(%) 시계열 — [(부문·품목 라벨, [(연도, 값)…])…]. period_year 있는 행만."""
    by_key: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        if r["metric"] != "utilization" or r["period_year"] is None:
            continue
        by_key.setdefault(_seg_label(r), []).append((r["period_year"], r["value"]))
    out = []
    for label, pts in by_key.items():
        pts.sort(key=lambda t: t[0])
        out.append((label, pts))
    out.sort(key=lambda t: -(t[1][-1][1] if t[1] else 0))  # 최신 가동률 내림차순
    return out


def production_table(rows: list[dict], metric: str, years: list[int]) -> list[dict]:
    """생산능력/생산실적 표 — 행=(부문·품목·단위), 열=연도. period_year 있는 행만."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        if r["metric"] != metric or r["period_year"] is None:
            continue
        key = (_seg_label(r), r.get("unit") or "")
        rec = by_key.setdefault(key, {"부문·품목": key[0], "단위": key[1] or "—"})
        rec[str(r["period_year"])] = r["value"]
    # 최신 연도 값 기준 내림차순
    latest = str(years[-1]) if years else None
    recs = list(by_key.values())
    recs.sort(key=lambda d: -(d.get(latest, 0) or 0)) if latest else None
    return recs


def supplementary_rows(rows: list[dict]) -> list[dict]:
    """비시계열 보조표(period_year=NULL) — 표준생산능력·가동가능일수 등."""
    out = []
    for r in rows:
        if r["period_year"] is not None:
            continue
        out.append({
            "지표": METRIC_LABELS.get(r["metric"], r["metric"]),
            "부문·품목": _seg_label(r), "항목": r.get("period_label") or "—",
            "값": r["value"], "단위": r.get("unit") or "—",
        })
    return out
