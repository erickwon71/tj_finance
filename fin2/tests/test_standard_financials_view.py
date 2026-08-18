"""Regression guard for the 2026-08-17 standard_financials <-> face_audit join defect.

The view's LEFT JOIN against face_audit omitted source_version, so v2 and v3 audit rows
both matched the same (corp, fy, fp, statement_type) key and every audited key was emitted
twice (244,585 keys observed 2026-08-18). Fixed by migration
`2026_08_standard_financials_view_source_version` (collector/db.py), which pins each UNION
ALL branch to the audit chain it actually displays (v3 branch -> source_version='v3', v2
branch -> source_version='v2'). See
docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md and
docs/qa/view_dup_baseline_2026-08-18.md.

Requires a live DB (DATABASE_URL) with the migrations applied, matching the pattern used by
other DB-backed tests in this repo (e.g. tests/test_download_5corps.py).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from collector.db import get_session


def _db_available() -> bool:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live DATABASE_URL")


def test_view_has_no_duplicate_keys():
    """standard_financials must emit exactly one row per (corp, fy, fp, type, version).

    Regression guard for the 2026-08-17 face_audit join defect: the LEFT JOIN omitted
    source_version, so v2 and v3 audit rows both matched and every audited key was
    emitted twice (244,585 keys). See docs/plans/gateb_view_source_version_join_fix_
    design_2026-08-17.md.
    """
    with get_session() as s:
        dupes = s.execute(text("""
            SELECT count(*) FROM (
                SELECT corp_code, fiscal_year, fiscal_period, statement_type, version,
                       count(*) AS n
                FROM standard_financials
                GROUP BY 1, 2, 3, 4, 5
                HAVING count(*) > 1
            ) t
        """)).scalar()
    assert dupes == 0, f"{dupes} duplicate (corp, fy, fp, type, version) keys in standard_financials"


def test_view_gate_b_status_matches_source_chain_audit():
    """gate_b_status on v3-sourced rows must equal the v3 face_audit result for that key.

    Guards against the mis-join re-attaching a v2 (or unrelated) audit result to a v3 row.
    """
    with get_session() as s:
        mismatches = s.execute(text("""
            SELECT count(*) FROM standard_financials sf
            JOIN std_financials_v3 v3
              USING (corp_code, fiscal_year, fiscal_period, statement_type)
            LEFT JOIN face_audit fa
              ON  fa.corp_code = sf.corp_code AND fa.fiscal_year = sf.fiscal_year
              AND fa.fiscal_period = sf.fiscal_period AND fa.statement_type = sf.statement_type
              AND NOT COALESCE(fa.is_stub, false) AND fa.source_version = 'v3'
            WHERE sf.gate_b_status IS DISTINCT FROM COALESCE(fa.gate_status, 'unaudited')
        """)).scalar()
    assert mismatches == 0, f"{mismatches} rows where gate_b_status disagrees with v3 face_audit"


def test_face_audit_queries_declare_source_version():
    """No code in app/ or scripts/ may query face_audit without a source_version filter.

    Regression guard for the 2026-08-17 finding that this join defect was the third R8
    ("wire every consumer") violation from the same commit (e6d0a04) — face_audit gained
    a source_version-aware PK but 3 of 4 readers weren't updated (docs/plans/gateb_view_
    source_version_join_fix_design_2026-08-17.md §1-C/§7). This is a lightweight source
    grep, not exhaustive SQL parsing: it flags any `FROM face_audit` / `JOIN face_audit`
    site in app/ or scripts/ whose surrounding text doesn't mention source_version.
    """
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"(FROM|JOIN)\s+face_audit\b", re.IGNORECASE)
    offenders = []
    for base in ("app", "scripts"):
        for path in (repo_root / base).rglob("*.py"):
            if "archive" in path.relative_to(repo_root).parts:
                continue  # one-off, already-run diagnostics — not maintained pipeline surface
            text_content = path.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text_content):
                # Look at a window around the match for a source_version mention —
                # the filter may be on a different line of the same SQL statement.
                window = text_content[max(0, m.start() - 400): m.end() + 400]
                if "source_version" not in window:
                    line_no = text_content.count("\n", 0, m.start()) + 1
                    offenders.append(f"{path.relative_to(repo_root)}:{line_no}")
    assert not offenders, (
        "face_audit queried without a nearby source_version filter: " + ", ".join(offenders)
    )
