"""R372 — tables carrying "[...]" bracket labels are real statements and must reach std_financials_v3
(docs/rules/20_layer3_map.md R372). DB test; skipped when the database or the row is unavailable."""
from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text

from fin2.layer3 import combine


def test_bracket_label_guard_is_gone_from_combine():
    src = inspect.getsource(combine)
    assert "label_raw ~ '^\\\\[.*\\\\]$'" not in src


def test_bracket_balance_sheet_reaches_std_separate():
    try:
        from collector.db import get_session
        with get_session() as s:
            row = s.execute(text(
                "select total_assets, total_liabilities, total_equity from std_financials_v3 "
                "where corp_code='00623184' and fiscal_year=2015 and fiscal_period='Q1' "
                "and statement_type='separate'")).fetchone()
    except Exception:
        pytest.skip("database not available")
    if row is None:
        pytest.skip("row not loaded")
    assert row[0] == 31_520_517_893
    assert row[1] == 2_858_649_349
    assert row[2] == 28_661_868_544
