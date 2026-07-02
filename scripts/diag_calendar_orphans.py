"""달력정규화(Layer 2) 유령/미래 분기 진단 — 수집 시작연도부터 전 연도 스캔.

`std_financials_calendar` 의 다음 이상행을 연도별로 집계한다:
  (A) ORPHAN CQ  : 대응하는 이산분기(std_financials_v2.is_discrete)가 없는 달력분기.
                   = calendarize 가 upsert-only 이던 시절, 기재정정으로 이산분기 period_end 가
                     바뀌면 예전 달력분기가 남아 생긴 유령행.
  (B) FUTURE CAL : period_end 가 오늘 이후인 달력행(아직 끝나지 않은 분기).
  (C) FUTURE DISC: period_end 가 오늘 이후인 이산분기(std_financials_v2). = 상류(분기환산/표준화)
                   에서 미래 분기말이 부여된 경우. calendarize 미래가드로 걸러지지만 상류 잔존은 별도.

usage:
  python scripts/diag_calendar_orphans.py            # 요약(연도별)
  python scripts/diag_calendar_orphans.py --detail   # 이상행 상세(corp 단위)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# 달력분기 토큰 ↔ period_end 월 매핑(calendar._MONTH_CQ 과 동일).
_CQ_CASE = ("CASE EXTRACT(MONTH FROM s.period_end) "
            "WHEN 3 THEN 'CQ1' WHEN 6 THEN 'CQ2' WHEN 9 THEN 'CQ3' WHEN 12 THEN 'CQ4' END")

# 이산분기가 없는 달력분기(orphan) 조건.
_ORPHAN_PRED = f"""
    cf.calendar_period LIKE 'CQ%' AND cf.version = 1
    AND NOT EXISTS (
        SELECT 1 FROM std_financials_v2 s
        WHERE s.corp_code = cf.corp_code AND s.statement_type = cf.statement_type
          AND s.version = 1 AND s.is_discrete = true AND NOT COALESCE(s.is_stub, false)
          AND s.period_end IS NOT NULL
          AND EXTRACT(YEAR FROM s.period_end) = cf.calendar_year
          AND {_CQ_CASE} = cf.calendar_period)
"""


def _rows(session, sql: str) -> list:
    return session.execute(text(sql)).fetchall()


def summary(session) -> int:
    print("===== (A) ORPHAN CQ 달력행 (연도별) =====")
    a = _rows(session, f"""
        SELECT cf.calendar_year, count(*) AS orphan_cq, count(DISTINCT cf.corp_code) AS corps
        FROM std_financials_calendar cf WHERE {_ORPHAN_PRED}
        GROUP BY 1 ORDER BY 1""")
    for y, n, c in a:
        print(f"  {y}: orphan={n:>4}  corps={c}")
    total_orphan = sum(n for _, n, _ in a)

    print("\n===== (B) FUTURE period_end 달력행 (period_end > today) =====")
    b = _rows(session, """
        SELECT calendar_year, calendar_period, count(*)
        FROM std_financials_calendar WHERE version=1 AND period_end > CURRENT_DATE
        GROUP BY 1,2 ORDER BY 1,2""")
    for y, p, n in b:
        print(f"  {y} {p}: {n}")
    total_future_cal = sum(n for *_, n in b)

    print("\n===== (C) FUTURE period_end 이산분기 (std_financials_v2, period_end > today) =====")
    c = _rows(session, """
        SELECT count(*) AS future_disc, count(DISTINCT corp_code) AS corps
        FROM std_financials_v2 WHERE version=1 AND is_discrete AND period_end > CURRENT_DATE""")
    fdisc, fcorps = c[0]

    print("\n----- 합계 -----")
    print(f"  (A) orphan CQ 달력행   : {total_orphan}   [파이프라인 불변식 — 0 이어야 함]")
    print(f"  (B) future 달력행      : {total_future_cal}   [파이프라인 불변식 — 0 이어야 함]")
    print(f"  (C) future 이산분기    : {fdisc} (corps={fcorps})   [상류/시드 데이터 플래그 — 참고]")
    # 게이트 = A + B(달력화가 통제하는 불변식). C 는 소스 데이터 이슈라 참고용(게이트 제외).
    return total_orphan + total_future_cal


def detail(session) -> None:
    print("===== ORPHAN CQ 상세 =====")
    for r in _rows(session, f"""
        SELECT cf.corp_code, c.corp_name, cf.statement_type, cf.calendar_year,
               cf.calendar_period, cf.period_end, cf.calculated_at
        FROM std_financials_calendar cf JOIN corporations c ON c.corp_code = cf.corp_code
        WHERE {_ORPHAN_PRED}
        ORDER BY cf.calendar_year, cf.corp_code, cf.statement_type, cf.calendar_period"""):
        print(f"  {r[3]} {r[4]} {r[2]:<12} {r[0]} {r[1]}  pe={r[5]}  calc={r[6]}")

    print("\n===== FUTURE 이산분기 상세 =====")
    for r in _rows(session, """
        SELECT s.corp_code, c.corp_name, c.fiscal_month, s.statement_type,
               s.fiscal_year, s.fiscal_period, s.period_end
        FROM std_financials_v2 s JOIN corporations c ON c.corp_code = s.corp_code
        WHERE s.version=1 AND s.is_discrete AND s.period_end > CURRENT_DATE
        ORDER BY s.corp_code, s.statement_type"""):
        print(f"  {r[0]} {r[1]} (fm={r[2]}) {r[3]:<12} FY{r[4]} {r[5]} pe={r[6]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true", help="이상행 corp 단위 상세 출력")
    args = ap.parse_args()
    with get_session() as s:
        if args.detail:
            detail(s)
        else:
            total = summary(s)
            print(f"\n{'✅ 이상 없음' if total == 0 else f'⚠ 이상행 총 {total}건'}")
            sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()
