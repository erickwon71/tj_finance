"""회사 일반현황 로더(Phase 2, PRD 13 ④) — 직원현황/타법인출자/임원보수(요약+개인별). UI 비의존."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from collector.db import get_session


def load_employee_stats(corp_code: str) -> tuple[Optional[int], list[dict]]:
    """최신 사업연도 직원현황(부문×성별 조합, 부문/성별 합계행 포함). 반환=(fiscal_year, rows)."""
    with get_session() as s:
        yr = s.execute(text(
            "SELECT max(fiscal_year) FROM employee_stats WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        if not yr:
            return None, []
        rows = s.execute(text("""
            SELECT division, sex, regular_count, contract_count, total_count,
                   avg_tenure_years, annual_salary_total, avg_salary, remark
            FROM employee_stats WHERE corp_code = :c AND fiscal_year = :y ORDER BY id
        """), {"c": corp_code, "y": yr}).mappings().fetchall()
        return yr, [dict(r) for r in rows]


def load_other_investments(corp_code: str) -> tuple[Optional[int], list[dict]]:
    """최신 사업연도 타법인 출자현황 — 기말장부가액 내림차순."""
    with get_session() as s:
        yr = s.execute(text(
            "SELECT max(fiscal_year) FROM other_investments WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        if not yr:
            return None, []
        rows = s.execute(text("""
            SELECT investee_name, purpose, first_acquired_date, first_acquired_amount,
                   end_qty, end_pct, end_book_value, investee_total_assets, investee_net_income
            FROM other_investments WHERE corp_code = :c AND fiscal_year = :y
            ORDER BY end_book_value DESC NULLS LAST
        """), {"c": corp_code, "y": yr}).mappings().fetchall()
        return yr, [dict(r) for r in rows]


def load_exec_pay(corp_code: str) -> tuple[Optional[int], Optional[dict], list[dict]]:
    """최신 사업연도 이사·감사 보수(요약, hmvAuditAllSttus) + 개인별 보수(5억 이상 상위5인,
    indvdlByPay — 미등기 고문/상담역 포함 가능, executives.compensation 과 별개 소스).
    반환=(fiscal_year, summary_dict|None, individual_rows)."""
    with get_session() as s:
        yr = s.execute(text(
            "SELECT max(fiscal_year) FROM exec_pay_summary WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        summary_row = None
        if yr:
            summary_row = s.execute(text("""
                SELECT total_exec_count, total_pay_amount, avg_pay_per_person
                FROM exec_pay_summary WHERE corp_code = :c AND fiscal_year = :y
            """), {"c": corp_code, "y": yr}).mappings().fetchone()
        summary = dict(summary_row) if summary_row else None

        ind_yr = yr or s.execute(text(
            "SELECT max(fiscal_year) FROM exec_pay_individual WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        individuals: list[dict] = []
        if ind_yr:
            ind_rows = s.execute(text("""
                SELECT person_name, position, total_pay_amount
                FROM exec_pay_individual WHERE corp_code = :c AND fiscal_year = :y
                ORDER BY total_pay_amount DESC NULLS LAST
            """), {"c": corp_code, "y": ind_yr}).mappings().fetchall()
            individuals = [dict(r) for r in ind_rows]
        return (yr or ind_yr), summary, individuals
