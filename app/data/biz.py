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

import re

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


# ── 부문·수출/내수 매출(Phase 3, metric='sales') ────────────────────────────────
# 한 기업의 매출 절엔 부문별/제품별/매출유형별/지역별 표가 공존해 같은 매출을 여러 축으로 재분해한다
# (naive 합산 시 중복). 그래서 최신 사업보고서 1건 안에서 (1)부문 구성용 = channel='합계' 실부문이
# 가장 많은 표, (2)수출비중용 = 수출·내수 채널을 모두 가진 표를 각각 골라 단일 table 로 스코프한다.
_SUBTOTAL_LABELS = {"합계", "계", "소계", "총계", "총액", "전체"}
# "패션부문  계" 같은 그룹 소계(부문명 + 공백 + 계) 판별 — 공백 앞에 오는 계는 소계 신호.
# '시계'/'온도계'(공백 없이 계로 끝나는 실제 품목)는 걸리지 않도록 공백 경계를 요구한다.
_GROUP_SUBTOTAL_RE = re.compile(r"\S\s+계$")


def _is_subtotal(label: str | None) -> bool:
    if not label:
        return False
    n = label.replace(" ", "")
    if n in _SUBTOTAL_LABELS:
        return True
    if n.endswith(("소계", "합계", "총계")):
        return True
    return bool(_GROUP_SUBTOTAL_RE.search(label.strip()))


def _sales_seg_label(r: dict) -> str:
    seg, item = (r.get("segment") or "").strip(), (r.get("item") or "").strip()
    if seg and item and seg != item and not _is_subtotal(item):
        return f"{seg} · {item}"
    return seg or item or "—"


def load_sales_composition(corp_code: str) -> dict:
    """corp 의 최신 사업보고서 매출표에서 부문 구성 + 수출비중을 구조화. UI 비의존.

    반환: {available, report_year, unit, years,
           segment_rows: [{label, by_year:{yr:val}}...],   # 부문별 구성(합계 채널, subtotal 제외)
           export_rows:  [{year, export, domestic, ratio_pct}...]}   # 수출비중(수출/내수 채널 표)
    """
    with get_session() as s:
        latest_rcept = s.execute(text(
            "SELECT rcept_no FROM biz_metrics WHERE corp_code=:c AND metric='sales' "
            "ORDER BY fiscal_year DESC, rcept_no DESC LIMIT 1"), {"c": corp_code}).scalar()
        if not latest_rcept:
            return {"available": False}
        rows = s.execute(text("""
            SELECT table_ord, channel, segment, item, period_year, value, unit
            FROM biz_metrics
            WHERE corp_code=:c AND metric='sales' AND rcept_no=:r AND period_year IS NOT NULL
            ORDER BY table_ord
        """), {"c": corp_code, "r": latest_rcept}).mappings().fetchall()
    recs = [dict(r) for r in rows]
    if not recs:
        return {"available": False}

    by_ord: dict[int, list[dict]] = {}
    for r in recs:
        by_ord.setdefault(r["table_ord"], []).append(r)

    # subtotal 은 segment 뿐 아니라 item 에도 올 수 있다(실측 한화 '화약제조업/소 계' — item='소 계'
    # 가 상품+제품+용역+기타 소계라 함께 세면 2배 오계상). 두 축 모두 subtotal 이면 제외.
    def _is_agg_row(r: dict) -> bool:
        return _is_subtotal(r["segment"]) or _is_subtotal(r.get("item"))

    # (1) 부문 구성 표 — channel='합계' 실부문(subtotal 제외) 수가 최다인 table_ord(동수면 최소 ord).
    def _n_real_segments(rs: list[dict]) -> int:
        return len({(r["segment"], r["item"]) for r in rs
                    if r["channel"] == "합계" and not _is_agg_row(r)})

    seg_ord = None
    best = 0
    for ordv in sorted(by_ord):
        n = _n_real_segments(by_ord[ordv])
        if n > best:
            best, seg_ord = n, ordv

    segment_rows: list[dict] = []
    seg_unit = None
    seg_years: set[int] = set()
    if seg_ord is not None:
        by_label: dict[str, dict] = {}
        for r in by_ord[seg_ord]:
            if r["channel"] != "합계" or _is_agg_row(r):
                continue
            seg_unit = seg_unit or r.get("unit")
            label = _sales_seg_label(r)
            rec = by_label.setdefault(label, {"label": label, "by_year": {}})
            rec["by_year"][r["period_year"]] = r["value"]
            seg_years.add(r["period_year"])
        # 최신 연도 값 기준 내림차순
        latest_y = max(seg_years) if seg_years else None
        segment_rows = sorted(by_label.values(),
                              key=lambda d: -(d["by_year"].get(latest_y, 0) or 0))

    # (2) 수출비중 표 — 수출·내수 채널을 모두 가진 table_ord(동수면 행수 최다, 최소 ord).
    exp_ord = None
    best_rows = 0
    for ordv in sorted(by_ord):
        chans = {r["channel"] for r in by_ord[ordv]}
        if {"수출", "내수"} <= chans:
            nr = len(by_ord[ordv])
            if nr > best_rows:
                best_rows, exp_ord = nr, ordv

    export_rows: list[dict] = []
    if exp_ord is not None:
        agg: dict[int, dict] = {}
        for r in by_ord[exp_ord]:
            if r["channel"] not in ("수출", "내수") or _is_agg_row(r):
                continue
            a = agg.setdefault(r["period_year"], {"export": 0.0, "domestic": 0.0})
            a["export" if r["channel"] == "수출" else "domestic"] += (r["value"] or 0)
        for yr in sorted(agg):
            e, d = agg[yr]["export"], agg[yr]["domestic"]
            tot = e + d
            export_rows.append({
                "year": yr, "export": e, "domestic": d,
                "ratio_pct": (e / tot * 100) if tot else None,
            })

    all_years = sorted(seg_years | {r["year"] for r in export_rows})
    return {
        "available": bool(segment_rows or export_rows),
        "report_year": max(all_years) if all_years else None,
        "unit": seg_unit,
        "years": all_years,
        "segment_rows": segment_rows,
        "export_rows": export_rows,
    }
