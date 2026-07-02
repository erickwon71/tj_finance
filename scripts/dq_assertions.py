"""I3 · 참조무결성/정합성 SQL 어서션 — 야간 상시 검사.

DB 전반의 '있어서는 안 되는' 상태를 SQL 어서션으로 점검한다. ERROR 위반이 1건이라도 있으면
종료코드 1(게이트/알림). WARN 은 참고 지표(정상 예외 존재)라 종료코드에 영향 없음.

달력 유령/미래 분기 검사는 `diag_calendar_orphans` 의 orphan 술어를 재사용한다.

usage:
  python scripts/dq_assertions.py            # 전 어서션 실행·요약
  python scripts/dq_assertions.py --sample   # 위반 표본행도 출력
"""
from __future__ import annotations

import argparse
import sys
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
        "desc": "std_financials_v2 에 미래 period_end(아직 끝나지 않은 기간)",
        "count": "SELECT count(*) FROM std_financials_v2 "
                 "WHERE version=1 AND period_end > CURRENT_DATE",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, period_end "
                  "FROM std_financials_v2 WHERE version=1 AND period_end > CURRENT_DATE "
                  "ORDER BY period_end DESC LIMIT 10",
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
        "desc": "자산총계 <= 0 (자산은 양수여야 함; as-reported 행 기준)",
        "count": "SELECT count(*) FROM std_financials_v2 WHERE version=1 "
                 "AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
                 "AND total_assets IS NOT NULL AND total_assets <= 0",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, total_assets "
                  "FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false) "
                  "AND NOT COALESCE(is_discrete,false) "
                  "AND total_assets IS NOT NULL AND total_assets <= 0 LIMIT 10",
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

    print(f"\nERROR 위반 어서션 {n_error_viol} · WARN 위반 어서션 {n_warn_viol}")
    print("✅ 무결성 OK" if n_error_viol == 0 else f"❌ ERROR 어서션 {n_error_viol}건 위반")
    sys.exit(1 if n_error_viol else 0)


if __name__ == "__main__":
    main()
