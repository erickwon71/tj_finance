"""R373 — a later table whose term (제N기) is older than the first table's is a prior-period table and is
not a current-period candidate (docs/rules/20_layer3_map.md R373). DB tests; skipped when unavailable."""
from __future__ import annotations

import pytest
from sqlalchemy import text


def _one(sql: str):
    try:
        from collector.db import get_session
        with get_session() as s:
            return s.execute(text(sql)).fetchone()
    except Exception:
        pytest.skip("database not available")


def test_vessel_fy2014_separate_uses_the_current_period_table():
    row = _one("select total_assets from std_financials_v3 where corp_code='00813389' and fiscal_year=2014 "
               "and fiscal_period='FY' and statement_type='separate'")
    if row is None:
        pytest.skip("row not loaded")
    assert row[0] == 47_021_944_045


def test_transition_period_table_is_not_the_current_period():
    row = _one("select revenue from std_financials_v3 where corp_code='01152470' and fiscal_year=2018 "
               "and fiscal_period='Q3' and statement_type='separate'")
    if row is None:
        pytest.skip("row not loaded")
    assert row[0] == 285_057_644_889
