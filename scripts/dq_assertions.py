"""I3 · 참조무결성/정합성 SQL 어서션 — 야간 상시 검사.

DB 전반의 '있어서는 안 되는' 상태를 SQL 어서션으로 점검한다. ERROR 위반이 1건이라도 있으면
종료코드 1(게이트/알림). WARN 은 참고 지표(정상 예외 존재)라 종료코드에 영향 없음.

달력 유령/미래 분기 검사는 `diag_calendar_orphans` 의 orphan 술어를 재사용한다.

C11(완전성 매트릭스): `check_completeness()` — 상장일 컬럼이 없어 "상장 이후 전체 이력"
재검증은 못하지만(6/25 전수검증이 그건 이미 증명함), 결산월 기준 이미 기한이 지난 최신
분기가 DB에 없는 기업을 매일 잡아 신규 공백(지연공시·정정드리프트)을 조기 발견한다.

usage:
  python scripts/dq_assertions.py            # 전 어서션 실행·요약
  python scripts/dq_assertions.py --sample   # 위반 표본행도 출력
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from diag_calendar_orphans import _ORPHAN_PRED   # scripts/ 는 실행 시 sys.path[0]

# 각 어서션: name / sev(ERROR|WARN) / desc / count SQL / sample SQL(선택)
CHECKS: list[dict] = [
    {
        "name": "future_period_std",
        "sev": "ERROR",
        "desc": "미래 period_end 인데 미격리(DQ<3) — 아직 끝나지 않은 기간이 소비계층에 노출",
        "count": "SELECT count(*) FROM std_financials_v2 "
                 "WHERE version=1 AND period_end > CURRENT_DATE AND COALESCE(data_quality,1) < 3",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, period_end "
                  "FROM std_financials_v2 WHERE version=1 AND period_end > CURRENT_DATE "
                  "AND COALESCE(data_quality,1) < 3 ORDER BY period_end DESC LIMIT 10",
    },
    {
        "name": "calendar_orphan_cq",
        "sev": "ERROR",
        "desc": "달력분기(CQ) 유령행 — 대응 이산분기 없음",
        "count": f"SELECT count(*) FROM std_financials_calendar cf WHERE {_ORPHAN_PRED}",
        "sample": f"SELECT cf.corp_code, cf.calendar_year, cf.calendar_period, cf.statement_type "
                  f"FROM std_financials_calendar cf WHERE {_ORPHAN_PRED} "
                  f"ORDER BY cf.calendar_year DESC LIMIT 10",
    },
    {
        "name": "calendar_future_period",
        "sev": "ERROR",
        "desc": "달력행에 미래 period_end(끝나지 않은 분기)",
        "count": "SELECT count(*) FROM std_financials_calendar "
                 "WHERE version=1 AND period_end > CURRENT_DATE",
        "sample": "SELECT corp_code, calendar_year, calendar_period, statement_type, period_end "
                  "FROM std_financials_calendar WHERE version=1 AND period_end > CURRENT_DATE LIMIT 10",
    },
    {
        "name": "calendar_cy_without_4cq",
        "sev": "ERROR",
        "desc": "달력연도(CY)인데 그 해 CQ1~CQ4 가 다 있지 않음",
        "count": """
            SELECT count(*) FROM std_financials_calendar cy WHERE cy.calendar_period='CY'
              AND cy.version=1 AND (
                SELECT count(*) FROM std_financials_calendar cq
                WHERE cq.corp_code=cy.corp_code AND cq.statement_type=cy.statement_type
                  AND cq.version=1 AND cq.calendar_year=cy.calendar_year
                  AND cq.calendar_period IN ('CQ1','CQ2','CQ3','CQ4')) < 4""",
        "sample": """
            SELECT cy.corp_code, cy.calendar_year, cy.statement_type FROM std_financials_calendar cy
            WHERE cy.calendar_period='CY' AND cy.version=1 AND (
                SELECT count(*) FROM std_financials_calendar cq
                WHERE cq.corp_code=cy.corp_code AND cq.statement_type=cy.statement_type
                  AND cq.version=1 AND cq.calendar_year=cy.calendar_year
                  AND cq.calendar_period IN ('CQ1','CQ2','CQ3','CQ4')) < 4 LIMIT 10""",
    },
    {
        "name": "nonpositive_total_assets",
        "sev": "ERROR",
        "desc": "자산총계 <= 0 인데 미격리(DQ<3) — 소비계층에 노출되는 불가값",
        "count": "SELECT count(*) FROM std_financials_v2 WHERE version=1 "
                 "AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
                 "AND total_assets IS NOT NULL AND total_assets <= 0 AND COALESCE(data_quality,1) < 3",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, total_assets "
                  "FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false) "
                  "AND NOT COALESCE(is_discrete,false) "
                  "AND total_assets IS NOT NULL AND total_assets <= 0 "
                  "AND COALESCE(data_quality,1) < 3 LIMIT 10",
    },
    {
        "name": "operating_income_eq_net_income",
        "sev": "WARN",
        "desc": "영업이익 == 순이익 (원단위 정확일치 = Track B 순이익 라인 오매핑 신호)",
        "count": "SELECT count(*) FROM std_financials_v2 WHERE version=1 "
                 "AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
                 "AND fiscal_period IN ('FY','Q1') "
                 "AND operating_income IS NOT NULL AND operating_income = net_income",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, operating_income "
                  "FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false) "
                  "AND NOT COALESCE(is_discrete,false) AND fiscal_period IN ('FY','Q1') "
                  "AND operating_income IS NOT NULL AND operating_income = net_income LIMIT 10",
    },
    {
        "name": "bs_identity_gt5pct",
        "sev": "WARN",
        "desc": "자산 ≠ 부채+자본 (5% 초과, =DQ3 항등식 위반)",
        "count": "SELECT count(*) FROM std_financials_v2 WHERE version=1 "
                 "AND COALESCE(data_quality,1) >= 3",
    },
    {
        "name": "consolidated_lt_separate_assets",
        "sev": "WARN",
        "desc": "연결 자산총계 < 별도 자산총계 (지주 통상 연결≥별도, 예외 존재)",
        "count": """
            SELECT count(*) FROM standard_financials con
            JOIN standard_financials sep ON sep.corp_code=con.corp_code
              AND sep.fiscal_year=con.fiscal_year AND sep.fiscal_period=con.fiscal_period
              AND sep.statement_type='separate'
            WHERE con.statement_type='consolidated' AND con.fiscal_period='FY'
              AND con.total_assets IS NOT NULL AND sep.total_assets IS NOT NULL
              AND con.total_assets < sep.total_assets * 0.999""",
        "sample": """
            SELECT con.corp_code, con.fiscal_year, con.total_assets AS con_assets,
                   sep.total_assets AS sep_assets
            FROM standard_financials con
            JOIN standard_financials sep ON sep.corp_code=con.corp_code
              AND sep.fiscal_year=con.fiscal_year AND sep.fiscal_period=con.fiscal_period
              AND sep.statement_type='separate'
            WHERE con.statement_type='consolidated' AND con.fiscal_period='FY'
              AND con.total_assets IS NOT NULL AND sep.total_assets IS NOT NULL
              AND con.total_assets < sep.total_assets * 0.999
            ORDER BY (sep.total_assets - con.total_assets) DESC LIMIT 10""",
    },
]


# ── C11 · 완전성(completeness) 매트릭스 ──────────────────────────────────────
# corporations 에 상장일이 없어 "상장 이후 전체 이력"을 재구성할 순 없다(6/25 전수검증이
# 그건 이미 1회 증명함 — verify_corp_sequential.py). 대신 **향후 신규 공백**(신규상장 누락·
# 지연공시·정정드리프트)을 잡는 최신성(staleness) 검사: 기업별 결산월 기준으로 "이미 법정
# 제출기한이 지난 가장 최근 분기"가 실제로 std_financials_v2 에 존재하는지 확인한다.
_DEADLINE_DAYS_BY_QUARTER = {1: 45, 2: 45, 3: 45, 4: 90}   # Q1/반기/Q3=45일, 사업보고서=90일
_GRACE_DAYS = 15                                            # 정정·DART 처리 지연 여유(오탐 방지)


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    total = y * 12 + (m - 1) + n
    return total // 12, total % 12 + 1


def _fiscal_quarter_ends(fiscal_month: int, fy_label_year: int) -> list[tuple[int, date]]:
    """결산월 fiscal_month, 회계연도 라벨 fy_label_year 의 4분기 말일 [(quarter_no, date), ...]."""
    fy_start_m = fiscal_month % 12 + 1
    fy_start_y = fy_label_year if fiscal_month == 12 else fy_label_year - 1
    out = []
    for k in (1, 2, 3, 4):
        y2, m2 = _add_months(fy_start_y, fy_start_m, 3 * k - 1)
        last_day = calendar.monthrange(y2, m2)[1]
        out.append((k, date(y2, m2, last_day)))
    return out


def _latest_due_period_end(fiscal_month: int, today: date) -> date:
    """오늘 기준, 이미 법정기한(+여유)이 지난 가장 최근 분기말일."""
    candidates: list[date] = []
    for fy_label_year in (today.year - 1, today.year, today.year + 1):
        for k, period_end in _fiscal_quarter_ends(fiscal_month, fy_label_year):
            deadline = period_end + timedelta(days=_DEADLINE_DAYS_BY_QUARTER[k] + _GRACE_DAYS)
            if deadline <= today:
                candidates.append(period_end)
    return max(candidates)


def check_completeness(session) -> tuple[int, list[tuple]]:
    """활성 정기보고 대상 기업 중, 이미 기한이 지난 최신 분기가 DB에 없는 기업 수·표본."""
    today = date.today()
    corps = session.execute(text(
        "SELECT corp_code, corp_name, fiscal_month, dart_modify_date FROM corporations "
        "WHERE is_active AND coverage_class = 'periodic'"
    )).fetchall()

    # is_stub 은 제외하지 않는다 — 결산월 변경 전환기간(예: 9월→12월)도 실제 제출·처리된 유효
    # 데이터라 "커버리지 있음"으로 인정해야 함(제외하면 아시아종묘류 오탐 발생, 2026-07-04 확인).
    latest = dict(session.execute(text(
        "SELECT corp_code, max(period_end) FROM std_financials_v2 "
        "WHERE version = 1 AND NOT COALESCE(is_discrete, false) "
        "GROUP BY corp_code"
    )).fetchall())

    stale: list[tuple] = []
    for corp_code, corp_name, fiscal_month, dart_modify_date in corps:
        expected = _latest_due_period_end(fiscal_month or 12, today)
        # 상장일 컬럼이 없어 대신 DART 레코드 최종변경일(신규상장 시 최근으로 찍힘)을 프록시로
        # 사용 — 그 시점이 기대 분기말보다 나중이면 "그 시점엔 존재하지 않았을 기업"이라 스킵
        # (신규상장 오탐 방지, 2026-07-04 확인 — 저스텍/스트라드비젼 등 6월~7월 신규상장 5사).
        if dart_modify_date:
            try:
                dmd = date(int(dart_modify_date[:4]), int(dart_modify_date[4:6]), int(dart_modify_date[6:8]))
                if dmd > expected:
                    continue
            except (ValueError, TypeError):
                pass
        have = latest.get(corp_code)
        if have is None or have < expected:
            stale.append((corp_code, corp_name, str(have), str(expected)))
    return len(stale), stale


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="위반 표본행도 출력")
    args = ap.parse_args()

    n_error_viol = 0
    n_warn_viol = 0
    print("===== DQ 어서션 =====")
    with get_session() as s:
        for chk in CHECKS:
            cnt = s.execute(text(chk["count"])).scalar() or 0
            mark = "✅" if cnt == 0 else ("❌" if chk["sev"] == "ERROR" else "⚠")
            print(f"  {mark} [{chk['sev']:<5}] {chk['name']:<32} 위반 {cnt:,} — {chk['desc']}")
            if cnt:
                if chk["sev"] == "ERROR":
                    n_error_viol += 1
                else:
                    n_warn_viol += 1
                if args.sample and chk.get("sample"):
                    for r in s.execute(text(chk["sample"])).fetchall():
                        print(f"        {tuple(r)}")

        n_stale, stale_sample = check_completeness(s)
        mark = "✅" if n_stale == 0 else "⚠"
        print(f"  {mark} [WARN ] {'completeness_staleness':<32} 위반 {n_stale:,} — "
              f"기한(+{_GRACE_DAYS}일 여유) 지난 최신분기 미존재 기업(C11)")
        if n_stale:
            n_warn_viol += 1
            if args.sample:
                for row in stale_sample[:10]:
                    print(f"        {row}")

    print(f"\nERROR 위반 어서션 {n_error_viol} · WARN 위반 어서션 {n_warn_viol}")
    print("✅ 무결성 OK" if n_error_viol == 0 else f"❌ ERROR 어서션 {n_error_viol}건 위반")
    sys.exit(1 if n_error_viol else 0)


if __name__ == "__main__":
    main()
