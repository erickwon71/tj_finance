"""verification scopes ('note' = note_lines, 'biz' = biz_section_tables) — load stamps, slots, issues.

Same throw-away database as test_verification_schema (cloned schema-only), so the live DB is
never written. Design: docs/plans/verification_note_biz_expansion_design_2026-10-27.md.
"""
from __future__ import annotations

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import errors  # noqa: E402

from fin2.tests.test_verification_schema import (  # noqa: E402,F401
    CORP, R1, _connect, _load, _one, db)

BASE = [("BS", "consolidated", "자산총계", 100), ("IS", "consolidated", "매출액", 50)]


def _load_note(conn, rcept: str, rows: list[tuple[str, int, int]]) -> None:
    """Mimic store_note_lines: delete the rcept, insert (basis, table_seq, value) rows, commit."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM note_lines WHERE rcept_no = %s", (rcept,))
        for i, (basis, seq, value) in enumerate(rows):
            cur.execute(
                "INSERT INTO note_lines (corp_code, rcept_no, report_fiscal_year, "
                "report_fiscal_period, statement, basis, label_raw, value_won, row_order, "
                "col_index, table_seq) VALUES (%s, %s, 2999, 'FY', 'note', %s, '현금', %s, %s, 0, %s)",
                (CORP, rcept, basis, value, i, seq))
    conn.commit()


def _load_biz(conn, rcept: str, rows: list[tuple[int, str, str]]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM biz_section_tables WHERE rcept_no = %s", (rcept,))
        for ord_, domain, cell in rows:
            cur.execute(
                "INSERT INTO biz_section_tables (corp_code, fiscal_year, rcept_no, table_ord, "
                "domain, metric, grid) VALUES (%s, 2999, %s, %s, %s, 'sales', %s::jsonb)",
                (CORP, rcept, ord_, domain, '[["a","%s"]]' % cell))
    conn.commit()


def _scope_slot(conn, scope: str) -> None:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO verification.scope_progress (scope, corp_code, fiscal_year, "
                    "fiscal_period, era, era_rank, corp_rank) VALUES (%s, %s, 2999, 'FY', "
                    "'2015+', 1, 1) ON CONFLICT DO NOTHING", (scope, CORP))
        cur.execute("INSERT INTO verification.scope_progress_filings (scope, rcept_no, corp_code, "
                    "fiscal_year, fiscal_period) VALUES (%s, %s, %s, 2999, 'FY') "
                    "ON CONFLICT DO NOTHING", (scope, R1, CORP))
    conn.commit()


def test_biz_and_note_loads_are_stamped_per_scope(db):
    admin = _connect(db)
    _load(admin, R1, BASE)                      # the report scope is stamped independently
    _load_biz(admin, R1, [(0, "sales", "10"), (1, "catalog", "20")])
    _load_note(admin, R1, [("consolidated", 1, 5), ("separate", 1, 6)])
    for scope in ("biz", "note"):
        assert _one(admin, "SELECT load_seq FROM verification.scope_loads "
                           "WHERE rcept_no=%s AND scope=%s", (R1, scope)) == (1,)

    _load_biz(admin, R1, [(0, "sales", "10"), (1, "catalog", "20")])      # identical reload
    assert _one(admin, "SELECT load_seq FROM verification.scope_loads "
                       "WHERE rcept_no=%s AND scope='biz'", (R1,)) == (1,)

    _load_biz(admin, R1, [(0, "sales", "11"), (1, "catalog", "20")])      # one cell changed
    assert _one(admin, "SELECT load_seq FROM verification.scope_loads "
                       "WHERE rcept_no=%s AND scope='biz'", (R1,)) == (2,)
    assert _one(admin, "SELECT changed_scopes FROM verification.scope_load_events "
                       "WHERE rcept_no=%s AND scope='biz' AND load_seq=2", (R1,)) == (["sales"],)

    _load_note(admin, R1, [("consolidated", 1, 5), ("separate", 1, 7)])
    assert _one(admin, "SELECT changed_scopes FROM verification.scope_load_events "
                       "WHERE rcept_no=%s AND scope='note' AND load_seq=2", (R1,)) == (["separate"],)
    # nothing leaked into the report stamp, nothing left dirty
    assert _one(admin, "SELECT load_seq FROM verification.filing_loads WHERE rcept_no=%s",
                (R1,)) == (1,)
    assert _one(admin, "SELECT count(*) FROM verification.scope_load_dirty") == (0,)
    admin.close()


def _add_issue(conn, scope: str, **kw):
    cols = {"scope": scope, "table_ref": "0", "statement": scope.upper() if scope != "report" else "BS",
            "account_label": "행", "error_type": "value_mismatch", "basis": None}
    cols.update(kw)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO verification.issues (corp_code, fiscal_year, fiscal_period, rcept_no, "
            "scope, table_ref, basis, statement, account_label, error_type) "
            "VALUES (%(c)s, 2999, 'FY', %(r)s, %(scope)s, %(table_ref)s, %(basis)s, %(statement)s, "
            "%(account_label)s, %(error_type)s) RETURNING issue_id", {"c": CORP, "r": R1, **cols})
        iid = cur.fetchone()[0]
    conn.commit()
    return iid


def test_scope_issue_shape_and_slot_isolation(db):
    admin = _connect(db)
    _scope_slot(admin, "biz")
    _scope_slot(admin, "note")
    report_before = _one(admin, "SELECT status, n_open_issues FROM verification.progress "
                                "WHERE corp_code=%s", (CORP,))

    biz_id = _add_issue(admin, "biz")                              # no basis
    note_id = _add_issue(admin, "note", basis="consolidated", table_ref="7")
    assert _one(admin, "SELECT found_load_seq FROM verification.issues WHERE issue_id=%s",
                (biz_id,)) == (2,)
    assert _one(admin, "SELECT status, n_open_issues FROM verification.scope_progress "
                       "WHERE scope='biz' AND corp_code=%s", (CORP,)) == ("has_issues", 1)
    assert _one(admin, "SELECT status FROM verification.scope_progress_filings "
                       "WHERE scope='note' AND rcept_no=%s", (R1,)) == ("has_issues",)
    # the report slot ignores scoped issues
    assert _one(admin, "SELECT status, n_open_issues FROM verification.progress "
                       "WHERE corp_code=%s", (CORP,)) == report_before

    with pytest.raises(errors.CheckViolation):                     # biz has no basis
        _add_issue(admin, "biz", basis="consolidated", table_ref="1")
    admin.rollback()
    with pytest.raises(errors.CheckViolation):                     # note needs its table
        _add_issue(admin, "note", basis="consolidated", table_ref=None, account_label="x")
    admin.rollback()
    with pytest.raises(errors.UniqueViolation):                    # same active cell twice
        _add_issue(admin, "biz")
    admin.rollback()
    assert note_id != biz_id
    admin.close()


def test_scope_issue_fixed_needs_scope_reload_and_lease_guard(db):
    admin = _connect(db)
    biz_id = _one(admin, "SELECT issue_id FROM verification.issues WHERE scope='biz' "
                         "AND status='open'")[0]
    fix = _connect(db, "tjf_fix", "camp_err_review")
    with fix.cursor() as cur:
        cur.execute("UPDATE verification.issues SET status='fixing' WHERE issue_id=%s", (biz_id,))
        cur.execute("UPDATE verification.issues SET fixed_parser_commit='f1x' WHERE issue_id=%s",
                    (biz_id,))
    fix.commit()
    # no reload since the issue was found -> fixed is refused
    with pytest.raises(psycopg2.Error):
        with fix.cursor() as cur:
            cur.execute("UPDATE verification.issues SET status='fixed' WHERE issue_id=%s", (biz_id,))
    fix.rollback()

    # a lease on the biz slot blocks the fix role's reload of biz tables
    with admin.cursor() as cur:
        cur.execute("UPDATE verification.scope_progress SET status='in_progress', "
                    "claimed_by='camp_run', lease_until=now()+interval '1 hour' "
                    "WHERE scope='biz' AND corp_code=%s", (CORP,))
    admin.commit()
    with pytest.raises(errors.LockNotAvailable):
        _load_biz(fix, R1, [(0, "sales", "12"), (1, "catalog", "20")])
    fix.rollback()
    with admin.cursor() as cur:
        cur.execute("UPDATE verification.scope_progress SET status='has_issues', lease_until=NULL "
                    "WHERE scope='biz' AND corp_code=%s", (CORP,))
    admin.commit()

    _load_biz(fix, R1, [(0, "sales", "12"), (1, "catalog", "20")])   # the real fix reload
    with fix.cursor() as cur:
        cur.execute("UPDATE verification.issues SET status='fixed' WHERE issue_id=%s", (biz_id,))
    fix.commit()
    assert _one(admin, "SELECT status, fixed_load_seq FROM verification.issues WHERE issue_id=%s",
                (biz_id,)) == ("fixed", 3)
    fix.close()
    admin.close()
