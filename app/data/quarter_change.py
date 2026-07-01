"""
분기 변화 로더 — 전 대상기업의 매출·영업이익 분기 증감(YoY/QoQ).

선택한 (달력연도, 분기)에 대해 활성 보통주 전체의 매출·영업이익을 조회하고,
직전분기(QoQ)·전년동기(YoY) 대비 증감액·증감률을 계산한다. 데이터는
`calendar_financials`(달력분기 CQ1~CQ4 이산)에서 오며, corp별 연결→별도 basis
폴백(요청 basis 의 해당 분기 행이 없으면 반대 basis)을 적용한다.

값은 raw 원(금액)·소수(비율). 표시 변환은 페이지에서.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from analyzer.ratio_engine import _growth_rate
from collector.db import get_session

_PERIODS = ("CQ1", "CQ2", "CQ3", "CQ4")


def available_calendar_years(statement_type: str = "consolidated") -> list[int]:
    """calendar_financials 에 분기 데이터가 있는 달력연도(내림차순)."""
    sql = """
        SELECT DISTINCT calendar_year
        FROM calendar_financials
        WHERE calendar_period IN ('CQ1', 'CQ2', 'CQ3', 'CQ4')
        ORDER BY calendar_year DESC
    """
    with get_session() as s:
        return [r[0] for r in s.execute(text(sql)).fetchall()]


def _total_targets() -> int:
    """전체 대상 기업수 = 활성 보통주(is_active + stock_code)."""
    sql = "SELECT count(*) FROM corporations WHERE is_active AND stock_code IS NOT NULL"
    with get_session() as s:
        return int(s.execute(text(sql)).scalar() or 0)


def _prev_periods(cal_year: int, quarter: str) -> tuple[tuple, tuple]:
    """(QoQ 직전분기), (YoY 전년동기) 의 (연도, 분기) 쌍."""
    qn = int(quarter[-1])
    qoq = (cal_year, f"CQ{qn - 1}") if qn > 1 else (cal_year - 1, "CQ4")
    yoy = (cal_year - 1, quarter)
    return qoq, yoy


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return (a - b) if (a is not None and b is not None) else None


def load_quarter_change(
    cal_year: int,
    quarter: str,
    statement_type: str = "consolidated",
) -> tuple[list[dict], int]:
    """
    선택 (연도, 분기)의 전 대상기업 매출·영업이익 + QoQ/YoY 증감(액·률).

    반환: (rows, total_targets)
      rows: 해당 분기 데이터가 있는 기업만. 각 행 =
        {corp_code, corp_name, stock_code, market, used_stmt,
         revenue, op,                              # 당분기 값(원)
         rev_qoq_amt, rev_qoq_pct, rev_yoy_amt, rev_yoy_pct,
         op_qoq_amt,  op_qoq_pct,  op_yoy_amt,  op_yoy_pct}
      total_targets: 전체 활성 보통주 수(분모).
    """
    if quarter not in _PERIODS:
        raise ValueError(f"quarter must be one of {_PERIODS}, got {quarter!r}")

    (qy, qp), (yy, yp) = _prev_periods(cal_year, quarter)
    other = "separate" if statement_type == "consolidated" else "consolidated"

    # tgt: 세 기간(당분기·직전분기·전년동기) × 두 basis 행. avail: 당분기가 요청 basis 에
    # 있는지(has_req) → 없으면 반대 basis 로 corp 단위 고정 폴백. 당분기 행이 있는 기업만 반환.
    sql = text("""
        WITH tgt AS (
            SELECT cf.corp_code, cf.calendar_year, cf.calendar_period,
                   cf.statement_type, cf.revenue, cf.operating_income
            FROM calendar_financials cf
            WHERE cf.statement_type IN (:stmt, :other)
              AND COALESCE(cf.data_quality, 1) < 3
              AND (cf.calendar_year, cf.calendar_period) IN (
                    (:cy, :cp), (:qy, :qp), (:yy, :yp))
        ),
        avail AS (
            SELECT corp_code, BOOL_OR(statement_type = :stmt) AS has_req
            FROM tgt
            WHERE calendar_year = :cy AND calendar_period = :cp
            GROUP BY corp_code
        )
        SELECT t.corp_code, t.calendar_year, t.calendar_period, t.statement_type,
               t.revenue, t.operating_income,
               c.corp_name, c.stock_code, c.market
        FROM tgt t
        JOIN avail a ON a.corp_code = t.corp_code
        JOIN corporations c ON c.corp_code = t.corp_code
        WHERE t.statement_type = CASE WHEN a.has_req THEN :stmt ELSE :other END
          AND c.is_active AND c.stock_code IS NOT NULL
    """)
    params = {
        "stmt": statement_type, "other": other,
        "cy": cal_year, "cp": quarter, "qy": qy, "qp": qp, "yy": yy, "yp": yp,
    }
    with get_session() as s:
        db_rows = s.execute(sql, params).mappings().fetchall()

    # corp별 pivot: 당분기/직전분기/전년동기 슬롯에 값 배치.
    by_corp: dict[str, dict] = {}
    for r in db_rows:
        cc = r["corp_code"]
        d = by_corp.get(cc)
        if d is None:
            d = by_corp[cc] = {
                "corp_code": cc, "corp_name": r["corp_name"],
                "stock_code": r["stock_code"], "market": r["market"],
                "used_stmt": r["statement_type"],
            }
        key = (r["calendar_year"], r["calendar_period"])
        if key == (cal_year, quarter):
            slot = "curr"
        elif key == (qy, qp):
            slot = "qoq"
        elif key == (yy, yp):
            slot = "yoy"
        else:
            continue
        d[f"{slot}_rev"] = r["revenue"]
        d[f"{slot}_op"] = r["operating_income"]

    rows: list[dict] = []
    for d in by_corp.values():
        if "curr_rev" not in d and "curr_op" not in d:
            continue  # 당분기 행 없음(방어)
        cur_rev, cur_op = d.get("curr_rev"), d.get("curr_op")
        qoq_rev, qoq_op = d.get("qoq_rev"), d.get("qoq_op")
        yoy_rev, yoy_op = d.get("yoy_rev"), d.get("yoy_op")
        rows.append({
            "corp_code": d["corp_code"], "corp_name": d["corp_name"],
            "stock_code": d["stock_code"], "market": d["market"],
            "used_stmt": d["used_stmt"],
            "revenue": cur_rev, "op": cur_op,
            "rev_qoq_amt": _diff(cur_rev, qoq_rev), "rev_qoq_pct": _growth_rate(cur_rev, qoq_rev),
            "rev_yoy_amt": _diff(cur_rev, yoy_rev), "rev_yoy_pct": _growth_rate(cur_rev, yoy_rev),
            "op_qoq_amt": _diff(cur_op, qoq_op), "op_qoq_pct": _growth_rate(cur_op, qoq_op),
            "op_yoy_amt": _diff(cur_op, yoy_op), "op_yoy_pct": _growth_rate(cur_op, yoy_op),
        })

    return rows, _total_targets()
