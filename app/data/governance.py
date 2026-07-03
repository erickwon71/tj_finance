"""지배구조 로더 — 임원 현황(executives). UI 비의존."""
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
