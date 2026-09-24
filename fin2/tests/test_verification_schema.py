"""verification schema — load hook, lease guard, pass demotion, issue state machine by role.

Runs against a throw-away database (tjf_vtest_schema) cloned schema-only from the three
public tables the hook touches, so the live DB is never written. Skipped when the local
Postgres or the source DB is not reachable.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import errors  # noqa: E402

from fin2.verification.schema import SCHEMA_SQL  # noqa: E402

TEST_DB = "tjf_vtest_schema"
SOURCE_DB = "tj_finance"

CORP = "99000001"
R1 = "29990101000001"   # original filing
R2 = "29990301000002"   # later amendment, same slot


def _run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def db():
    if not shutil.which("pg_dump") or not shutil.which("createdb"):
        pytest.skip("postgres client tools not available")
    try:
        psycopg2.connect(dbname=SOURCE_DB).close()
    except psycopg2.OperationalError:
        pytest.skip("local postgres not reachable")
    _run("dropdb", "--if-exists", "--force", TEST_DB)
    _run("createdb", TEST_DB)
    dump = subprocess.run(
        ["pg_dump", "--schema-only", "-t", "corporations", "-t", "filings",
         "-t", "report_lines", SOURCE_DB], check=True, capture_output=True, text=True).stdout
    # The live report_lines carries the verification triggers; they are recreated by
    # schema.sql below, and would fail here because their functions do not exist yet.
    dump = "\n".join(l for l in dump.splitlines() if "verification." not in l)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", TEST_DB],
                   input=dump, check=True, capture_output=True, text=True)
    conn = psycopg2.connect(dbname=TEST_DB)
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute("INSERT INTO corporations (corp_code, corp_name, is_active) "
                    "VALUES (%s, 'TEST', true)", (CORP,))
        for rcept, amend in ((R1, False), (R2, True)):
            cur.execute(
                "INSERT INTO filings (rcept_no, corp_code, report_type, fiscal_year, "
                "fiscal_period, is_amendment) VALUES (%s, %s, 'annual', 2999, 'FY', %s)",
                (rcept, CORP, amend))
        cur.execute("INSERT INTO verification.progress (corp_code, fiscal_year, fiscal_period, "
                    "era, era_rank, corp_rank) VALUES (%s, 2999, 'FY', '2015+', 1, 1)", (CORP,))
        cur.execute("INSERT INTO verification.progress_filings (rcept_no, corp_code, "
                    "fiscal_year, fiscal_period) VALUES (%s, %s, 2999, 'FY')", (R1, CORP))
    conn.commit()
    conn.close()
    yield TEST_DB
    _run("dropdb", "--if-exists", "--force", TEST_DB)


def _connect(db, role: str | None = None, actor: str = "test"):
    conn = psycopg2.connect(dbname=db, user=role) if role else psycopg2.connect(dbname=db)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('verification.actor', %s, false)", (actor,))
        cur.execute("SELECT set_config('verification.parser_commit', 'abc123', false)")
    conn.commit()
    return conn


def _load(conn, rcept: str, rows: list[tuple[str, str, str, int]]) -> None:
    """Mimic store_report_lines: delete the rcept, insert its rows, commit."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM report_lines WHERE rcept_no = %s", (rcept,))
        for i, (stmt, basis, label, value) in enumerate(rows):
            cur.execute(
                "INSERT INTO report_lines (corp_code, rcept_no, report_fiscal_year, "
                "report_fiscal_period, statement, basis, label_raw, value_won, row_order, "
                "col_index) VALUES (%s, %s, 2999, 'FY', %s, %s, %s, %s, %s, 0)",
                (CORP, rcept, stmt, basis, label, value, i))
    conn.commit()


def _one(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row


BASE = [("BS", "consolidated", "자산총계", 100), ("IS", "consolidated", "매출액", 50)]


def test_load_hook_versions_by_content(db):
    admin = _connect(db)
    _load(admin, R1, BASE)
    assert _one(admin, "SELECT load_seq, parser_commit, loaded_by FROM verification.filing_loads "
                       "WHERE rcept_no = %s", (R1,)) == (1, "abc123", "test")

    _load(admin, R1, BASE)                      # identical re-parse: no new version
    assert _one(admin, "SELECT load_seq FROM verification.filing_loads WHERE rcept_no=%s",
                (R1,)) == (1,)

    changed = [("BS", "consolidated", "자산총계", 101), BASE[1]]
    _load(admin, R1, changed)
    assert _one(admin, "SELECT load_seq FROM verification.filing_loads WHERE rcept_no=%s",
                (R1,)) == (2,)
    assert _one(admin, "SELECT changed_scopes FROM verification.filing_load_events "
                       "WHERE rcept_no=%s AND load_seq=2", (R1,)) == (["con-bs"],)
    assert _one(admin, "SELECT count(*) FROM verification.load_dirty") == (0,)
    admin.close()


def test_reload_after_pass_demotes_filing_and_slot(db):
    admin = _connect(db)
    with admin.cursor() as cur:
        cur.execute("UPDATE verification.progress_filings SET status='passed' WHERE rcept_no=%s",
                    (R1,))
        cur.execute("SELECT verification.refresh_slot(%s, 2999, 'FY')", (CORP,))
    admin.commit()
    assert _one(admin, "SELECT status FROM verification.progress WHERE corp_code=%s",
                (CORP,)) == ("passed",)

    _load(admin, R1, [("BS", "consolidated", "자산총계", 102), BASE[1]])
    assert _one(admin, "SELECT status FROM verification.progress_filings WHERE rcept_no=%s",
                (R1,)) == ("pending",)
    assert _one(admin, "SELECT status FROM verification.progress WHERE corp_code=%s",
                (CORP,)) == ("pending",)
    assert _one(admin, "SELECT count(*) FROM verification.progress_events "
                       "WHERE action='reloaded_after_pass'") == (1,)
    admin.close()


def test_lease_blocks_fix_role_only(db):
    admin = _connect(db)
    with admin.cursor() as cur:
        cur.execute("UPDATE verification.progress SET status='in_progress', claimed_by='camp_run', "
                    "lease_until = now() + interval '1 hour' WHERE corp_code=%s", (CORP,))
    admin.commit()

    fix = _connect(db, "tjf_fix", "camp_err_review")
    with pytest.raises(errors.LockNotAvailable):
        _load(fix, R1, [("BS", "consolidated", "자산총계", 999), BASE[1]])
    fix.rollback()
    # The identical content is fine even under a lease (nothing the reviewer sees changes).
    seq_before = _one(admin, "SELECT load_seq FROM verification.filing_loads WHERE rcept_no=%s",
                      (R1,))
    rows_now = [("BS", "consolidated", "자산총계", 102), BASE[1]]
    _load(fix, R1, rows_now)
    assert _one(admin, "SELECT load_seq FROM verification.filing_loads WHERE rcept_no=%s",
                (R1,)) == seq_before
    fix.close()

    with admin.cursor() as cur:
        cur.execute("UPDATE verification.progress SET status='pending', claimed_by=NULL, "
                    "lease_until=NULL WHERE corp_code=%s", (CORP,))
    admin.commit()
    admin.close()


def test_verify_role_cannot_write_public(db):
    ver = _connect(db, "tjf_verify", "camp_run")
    with pytest.raises(errors.InsufficientPrivilege):
        _load(ver, R1, BASE)
    ver.rollback()
    with pytest.raises(errors.InsufficientPrivilege):
        with ver.cursor() as cur:
            cur.execute("UPDATE verification.issue_events SET actor='x'")
    ver.rollback()
    ver.close()


def _add_issue(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO verification.issues (corp_code, fiscal_year, fiscal_period, rcept_no, "
            "basis, statement, account_label, db_value, source_value, source_value_raw, "
            "source_unit, error_type) VALUES (%s, 2999, 'FY', %s, 'consolidated', 'BS', "
            "'자산총계', 102, 100, '100', '원', 'value_mismatch') RETURNING issue_id",
            (CORP, R1))
        issue_id = cur.fetchone()[0]
    conn.commit()
    return issue_id


def _set_status(conn, issue_id: int, status: str, *, evidence: str | None = None,
                commit_sha: str | None = None) -> None:
    with conn.cursor() as cur:
        if evidence:
            cur.execute("SELECT set_config('verification.evidence', %s, true)", (evidence,))
        cur.execute("UPDATE verification.issues SET status=%s, "
                    "fixed_parser_commit=coalesce(%s, fixed_parser_commit) WHERE issue_id=%s",
                    (status, commit_sha, issue_id))
    conn.commit()


def test_issue_state_machine_by_role(db):
    ver = _connect(db, "tjf_verify", "camp_run")
    fix = _connect(db, "tjf_fix", "camp_err_review")
    admin = _connect(db)

    with pytest.raises((errors.RaiseException, errors.InsufficientPrivilege)):  # fix: no issues
        _add_issue(fix)
    fix.rollback()

    issue = _add_issue(ver)
    found = _one(admin, "SELECT found_load_seq FROM verification.issues WHERE issue_id=%s",
                 (issue,))[0]
    assert found is not None
    assert _one(admin, "SELECT status, n_open_issues FROM verification.progress "
                       "WHERE corp_code=%s", (CORP,)) == ("has_issues", 1)
    assert _one(admin, "SELECT status FROM verification.progress_filings WHERE rcept_no=%s",
                (R1,)) == ("has_issues",)

    with pytest.raises(errors.RaiseException):     # verify cannot take the fixer's step
        _set_status(ver, issue, "fixing")
    ver.rollback()

    _set_status(fix, issue, "fixing")
    with pytest.raises(errors.RaiseException):     # fixed needs an actual data change
        _set_status(fix, issue, "fixed", commit_sha="def456")
    fix.rollback()

    _load(fix, R1, [("BS", "consolidated", "자산총계", 100), BASE[1]])
    _set_status(fix, issue, "fixed", commit_sha="def456")
    assert _one(admin, "SELECT fixed_load_seq > found_load_seq FROM verification.issues "
                       "WHERE issue_id=%s", (issue,)) == (True,)

    with pytest.raises(errors.RaiseException):     # fix cannot close its own work
        _set_status(fix, issue, "closed")
    fix.rollback()
    with pytest.raises(errors.RaiseException):     # reopen needs evidence
        _set_status(ver, issue, "reopened")
    ver.rollback()

    _set_status(ver, issue, "closed")
    assert _one(admin, "SELECT status, n_open_issues FROM verification.progress "
                       "WHERE corp_code=%s", (CORP,)) == ("pending", 0)
    # The filing goes back to pending so the changed scopes get re-compared.
    assert _one(admin, "SELECT status FROM verification.progress_filings WHERE rcept_no=%s",
                (R1,)) == ("pending",)

    _set_status(ver, issue, "reopened", evidence="regression seen on recheck")
    assert _one(admin, "SELECT array_agg(to_status ORDER BY event_id) FROM "
                       "verification.issue_events WHERE issue_id=%s", (issue,)) == (
        ["open", "fixing", "fixed", "closed", "reopened"],)
    for c in (ver, fix, admin):
        c.close()


def test_new_amendment_joins_slot(db):
    admin = _connect(db)
    _load(admin, R2, BASE)
    assert _one(admin, "SELECT corp_code, seq_in_slot, is_amendment, status FROM "
                       "verification.progress_filings WHERE rcept_no=%s", (R2,)) == (
        CORP, 2, True, "pending")
    assert _one(admin, "SELECT count(*) FROM verification.progress_events "
                       "WHERE action='filing_joined' AND rcept_no=%s", (R2,)) == (1,)
    admin.close()
