"""달력정규화(Layer 2) 유령/미래 분기 진단 — 수집 시작연도부터 전 연도 스캔.

`std_financials_calendar` 의 다음 이상행을 연도별로 집계한다:
  (A) ORPHAN CQ  : 그 CQ 를 만든 근거 as-filed 행(source_lineage 가 가리키는
                   std_financials_v3 행)이 더는 존재하지 않거나 period_end 가 바뀌어
                   그 달력분기 슬롯에 더 이상 대응하지 않는 달력분기. = calendarize_v3 가
                   corp+basis 단위 delete-then-insert 이므로 그 corp+basis 를 다시 돌리지
                   않은 채 std_v3 쪽만 바뀌면(기재정정·재백필) 남는 유령행.
  (B) FUTURE CAL : period_end 가 오늘 이후인 달력행(아직 끝나지 않은 분기).
  (C) FUTURE ASFILED: period_end 가 오늘 이후인 as-filed 행(std_financials_v3). 상류에서
                   미래 분기말이 부여된 경우 — calendarize_v3 의 `_is_calendarizable_end()`
                   가드로 달력화 자체는 막히지만 상류 잔존은 별도 신호. dq_assertions.py
                   의 `future_period_std` 어서션과 동일 술어(중복 아님 — 이쪽은 연도별
                   집계·corp 상세용, 그쪽은 게이트용).

usage:
  python scripts/diag_calendar_orphans.py            # 요약(연도별)
  python scripts/diag_calendar_orphans.py --detail   # 이상행 상세(corp 단위)

★2026-09-02(calendar_v3_migration_scoping_2026-09-02.md §3(c)) — std_financials_v2
DROP(2026-09-01) 후 (A)(C) 가 죽은 테이블을 읽어 `dq_assertions.py::calendar_orphan_cq`
가 상시 SKIP 이던 것을 std_financials_v3 기반으로 재작성해 복구. 이산분기는 이제 DB에
저장되지 않으므로(calendar_v3.py 설계, 메모리 계산만) (A)는 "이산분기 존재 여부"가 아니라
"그 CQ 를 만든 as-filed 행이 지금도 같은 슬롯을 뒷받침하는가"로 판정식 자체가 바뀌었다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# 달력분기 토큰 ↔ period_end 월 매핑(calendar._MONTH_CQ 과 동일).
_CQ_CASE = ("CASE EXTRACT(MONTH FROM vend.period_end) "
            "WHEN 3 THEN 'CQ1' WHEN 6 THEN 'CQ2' WHEN 9 THEN 'CQ3' WHEN 12 THEN 'CQ4' END")

# cf.source_lineage(예 [[2024,'Q2']])의 fp 는 **이산분기 라벨**(Q1~Q4) — std_financials_v3
# 에 그대로 있는 값이 아니다(v3 는 Q1/H1/Q3/FY 누적행만 저장). quarterly.py::_QUARTER_SPEC
# 과 동일한 매핑으로 그 이산분기를 만든 "말(end) 누적행"·"차감(sub) 누적행" fiscal_period 를
# 재구성해야 한다: Q1=Q1(차감없음) / Q2=H1−Q1 / Q3=Q3−H1 / Q4=FY−Q3.
_END_FP = ("CASE cf.source_lineage->0->>1 "
           "WHEN 'Q1' THEN 'Q1' WHEN 'Q2' THEN 'H1' WHEN 'Q3' THEN 'Q3' WHEN 'Q4' THEN 'FY' END")
_SUB_FP = ("CASE cf.source_lineage->0->>1 "
           "WHEN 'Q2' THEN 'Q1' WHEN 'Q3' THEN 'H1' WHEN 'Q4' THEN 'Q3' END")  # Q1 은 NULL(차감없음)

# orphan 조건 — 그 이산분기를 만든 end/sub 누적행이(위 매핑) std_financials_v3 에 지금도
# 둘 다(Q1 은 end 만) 있고, end 의 period_end 가 이 칸(calendar_year, calendar_period)에
# 여전히 대응해야 orphan 아님 — 하나라도 사라졌으면(기재정정 등) orphan. CY 는 범위 밖
# (CQ1~4 orphan 여부로 이미 간접 커버되고, `calendar_cy_without_4cq` 어서션이 구조를
# 별도로 검증).
_ORPHAN_PRED = f"""
    cf.calendar_period LIKE 'CQ%' AND cf.version = 1
    AND NOT EXISTS (
        SELECT 1 FROM std_financials_v3 vend
        WHERE vend.corp_code = cf.corp_code AND vend.statement_type = cf.statement_type
          AND vend.fiscal_year = (cf.source_lineage->0->>0)::int
          AND vend.fiscal_period = ({_END_FP})
          AND vend.period_end IS NOT NULL
          AND EXTRACT(YEAR FROM vend.period_end) = cf.calendar_year
          AND {_CQ_CASE} = cf.calendar_period
          AND (
                ({_SUB_FP}) IS NULL
                OR EXISTS (
                    SELECT 1 FROM std_financials_v3 vsub
                    WHERE vsub.corp_code = cf.corp_code AND vsub.statement_type = cf.statement_type
                      AND vsub.fiscal_year = (cf.source_lineage->0->>0)::int
                      AND vsub.fiscal_period = ({_SUB_FP})))
    )
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

    print("\n===== (C) FUTURE period_end as-filed 행 (std_financials_v3, period_end > today) =====")
    c = _rows(session, """
        SELECT count(*) AS future_asfiled, count(DISTINCT corp_code) AS corps
        FROM std_financials_v3 WHERE period_end > CURRENT_DATE""")
    fdisc, fcorps = c[0]

    print("\n----- 합계 -----")
    print(f"  (A) orphan CQ 달력행     : {total_orphan}   [파이프라인 불변식 — 0 이어야 함]")
    print(f"  (B) future 달력행        : {total_future_cal}   [파이프라인 불변식 — 0 이어야 함]")
    print(f"  (C) future as-filed 행   : {fdisc} (corps={fcorps})   [상류/시드 데이터 플래그 — 참고]")
    # 게이트 = A + B(달력화가 통제하는 불변식). C 는 소스 데이터 이슈라 참고용(게이트 제외,
    # dq_assertions.py::future_period_std 가 이미 이 신호를 ERROR 게이트로 별도 커버).
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

    print("\n===== FUTURE as-filed 행 상세 =====")
    for r in _rows(session, """
        SELECT s.corp_code, c.corp_name, c.fiscal_month, s.statement_type,
               s.fiscal_year, s.fiscal_period, s.period_end
        FROM std_financials_v3 s JOIN corporations c ON c.corp_code = s.corp_code
        WHERE s.period_end > CURRENT_DATE
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
