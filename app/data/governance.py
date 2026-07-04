"""지배구조 로더 — 임원 현황(executives) + 대주주/지분(B3). UI 비의존."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from collector.db import get_session


def load_executives(corp_code: str) -> tuple[Optional[int], list[dict]]:
    """최신 사업연도 임원 로스터. 반환=(fiscal_year, [로우...]). 없으면 (None, [])."""
    with get_session() as s:
        yr = s.execute(text(
            "SELECT max(fiscal_year) FROM executives WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        if not yr:
            return None, []
        rows = s.execute(text("""
            SELECT name, position, is_registered, is_fulltime, gender, birth_ym,
                   responsibility, shareholder_rel, tenure_period, main_career
            FROM executives WHERE corp_code = :c AND fiscal_year = :y ORDER BY id
        """), {"c": corp_code, "y": yr}).mappings().fetchall()
        return yr, [dict(r) for r in rows]


def load_ownership(corp_code: str) -> tuple[Optional[int], list[dict], Optional[dict], list[dict]]:
    """
    최신 사업연도 지분 현황. 반환=(fiscal_year, 대주주목록, 소액주주요약dict|None, 변동이력목록).

    주의: shareholder_changes 는 사업보고서가 "최근 수년 변동이력"을 통째로 다시 보여주는 관례라
    한 연도 조회만으로도 과거 변동 전부가 나온다(중복 아님 — DART 원본 구조).
    """
    with get_session() as s:
        yr = s.execute(text(
            "SELECT max(fiscal_year) FROM major_shareholders WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        if not yr:
            return None, [], None, []
        holders = s.execute(text("""
            SELECT name, relation, stock_kind, shares_end, pct_end, remark
            FROM major_shareholders WHERE corp_code = :c AND fiscal_year = :y
            ORDER BY pct_end DESC NULLS LAST
        """), {"c": corp_code, "y": yr}).mappings().fetchall()

        retail = s.execute(text("""
            SELECT holder_count, holder_total_count, holder_rate_pct,
                   held_shares, total_shares, held_rate_pct
            FROM retail_ownership WHERE corp_code = :c AND fiscal_year = :y
        """), {"c": corp_code, "y": yr}).mappings().fetchone()

        changes = s.execute(text("""
            SELECT change_on, holder_name, pct, cause
            FROM shareholder_changes WHERE corp_code = :c AND fiscal_year = :y
            ORDER BY change_on DESC
        """), {"c": corp_code, "y": yr}).mappings().fetchall()

        return yr, [dict(r) for r in holders], (dict(retail) if retail else None), [dict(r) for r in changes]
