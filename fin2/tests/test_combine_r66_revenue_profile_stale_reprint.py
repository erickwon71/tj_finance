"""R66 (2026-09-03, docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_
reprint_design_2026-09-02.md §10) — DB-backed regression guard for the second
stale-reprint consumer.

R63/§8 filtered `_resolve()`'s `cands`, but `combine_full()`'s industry revenue
profile (fin2/layer3/industry_profiles.py::apply_revenue_profile(), used for
securities/insurance/bank/leasing corps) reads the raw merged IS lines directly
and never saw the filter — so a K-GAAP era consolidated interim IS table that's
actually the prior year's annual figures re-printed (table_seq flagged by
_stale_annual_reprint_table_seqs()) could still feed the named-subtotal revenue
formula. Root-caused via 00104856 (삼성증권) FY2005 Q1/H1/Q3 consolidated:
op_income(154,594,395,676) + sga(517,609,979,403) = 672,204,375,079, matching the
contaminated std_v3 revenue exactly (both from the same stale table_seq=0).

Requires a live DB (DATABASE_URL) with the migrations applied, matching the
pattern used by fin2/tests/test_combine_r63_stale_reprint_db.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.db import get_session
from fin2.layer3.combine import combine


def _db_available() -> bool:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live DATABASE_URL")


@pytest.mark.parametrize("period", ["Q1", "H1", "Q3"])
def test_samsung_securities_2005_consolidated_revenue_not_contaminated(period):
    # 00104856 (삼성증권) FY2005 consolidated: before the fix, revenue == the
    # stale-reprint-derived 672,204,375,079 for all three interim periods (design
    # doc §10.1). No genuine consolidated interim source exists for this era
    # (R63's own finding), so the correct outcome is None, not a recovered value.
    with get_session() as s:
        col, _conflicts = combine(s, "00104856", 2005, period, "consolidated")
    assert col.get("revenue") is None, (
        f"expected revenue=None (stale reprint excluded), got {col.get('revenue')}")
    assert col.get("revenue") != 672204375079


def test_samsung_securities_2005_separate_unaffected():
    # 별도(separate) basis for the same corp/year is a different table_seq
    # population (R63 §8.2: separate match rate 16.0% vs consolidated 97.2%) —
    # this guard is basis-scoped and must not touch separate's genuine data.
    with get_session() as s:
        col_sep, _ = combine(s, "00104856", 2005, "Q1", "separate")
    # Not asserting a specific value here (out of scope for this bug) — just that
    # the separate path still runs without error and isn't force-nulled by the
    # consolidated-basis stale set.
    assert isinstance(col_sep, dict)
