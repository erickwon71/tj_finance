"""Machine pass + model gate against a throw-away DB (real tjf_verify role).

Design: docs/plans/verification_machine_compare_design_2026-09-24.md
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from sqlalchemy import create_engine, event, text  # noqa: E402

from fin2.tests.test_verification_ops import TABLES, _run  # noqa: E402
from fin2.verification import machine_pass, ops, runner  # noqa: E402
from fin2.verification import decisions as dz  # noqa: E402
from fin2.verification.ops import Slot  # noqa: E402
from fin2.verification.schema import SCHEMA_SQL  # noqa: E402

TEST_DB = "tjf_vtest_machine"
CORP = "99000003"
R_OK, R_BAD, R_SIGN = "29990101000021", "29990101000022", "29990101000023"
SLOT_OK, SLOT_BAD = Slot(CORP, 2024, "FY"), Slot(CORP, 2023, "FY")

SIGN_XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>4. 재무제표</TITLE>
<TABLE><TR><TD>자본변동표</TD></TR></TABLE>
<TABLE><TR><TD>구분</TD><TD>자본금</TD><TD>이익잉여금</TD></TR>
<TR><TD>2022.01.01 (기초자본)</TD><TD>100</TD><TD>50</TD></TR>
<TR><TD>배당금지급</TD><TD></TD><TD>7</TD></TR>
<TR><TD>2022.12.31 (기말자본)</TD><TD>100</TD><TD>43</TD></TR></TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""

XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE>2. 연결재무제표</TITLE>
<TABLE><TR><TD>연결 재무상태표</TD></TR></TABLE>
<TABLE><TR><TD>과목</TD><TD>당기</TD><TD>전기</TD></TR>
<TR><TD>자산총계</TD><TD>1,000</TD><TD>900</TD></TR>
<TR><TD>부채총계</TD><TD>400</TD><TD>300</TD></TR>
<TR><TD>자본총계</TD><TD>600</TD><TD>600</TD></TR></TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def _engine(user: str | None, actor: str):
    eng = create_engine(f"postgresql://{user + '@' if user else ''}/{TEST_DB}")

    @event.listens_for(eng, "connect")
    def _ident(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("SELECT set_config('verification.actor', %s, false)", (actor,))
        cur.execute("SELECT set_config('verification.parser_commit', 'c0ffee', false)")
        dbapi_conn.commit()
        cur.close()
    return eng


@pytest.fixture(scope="module")
def engines(tmp_path_factory):
    if not shutil.which("pg_dump"):
        pytest.skip("postgres client tools not available")
    try:
        psycopg2.connect(dbname="tj_finance").close()
    except psycopg2.OperationalError:
        pytest.skip("local postgres not reachable")
    _run("dropdb", "--if-exists", "--force", TEST_DB)
    _run("createdb", TEST_DB)
    args = ["pg_dump", "--schema-only"]
    for t in TABLES:
        args += ["-t", t]
    dump = subprocess.run(args + ["tj_finance"], check=True, capture_output=True, text=True).stdout
    dump = "\n".join(l for l in dump.splitlines() if "verification." not in l)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", TEST_DB], input=dump,
                   check=True, capture_output=True, text=True)
    xml = tmp_path_factory.mktemp("xml") / "f.xml"
    xml.write_text(XML, encoding="utf-8")
    conn = psycopg2.connect(dbname=TEST_DB)
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute("INSERT INTO corporations (corp_code, corp_name, market, stock_code, "
                    "is_active, coverage_class) VALUES (%s, 'TESTCO', 'KOSPI', '123460', true, "
                    "'periodic')", (CORP,))
        # R_OK loads the source faithfully; R_BAD took the prior-year column for 자산총계.
        for r, fy, assets in ((R_OK, 2024, 1000), (R_BAD, 2023, 900)):
            cur.execute("INSERT INTO filings (rcept_no, corp_code, report_type, fiscal_year, "
                        "fiscal_period, is_amendment, filed_at, report_nm) VALUES "
                        "(%s, %s, 'annual', %s, 'FY', false, '2025-03-01', '사업보고서')", (r, CORP, fy))
            for i, (lab, v) in enumerate((("자산총계", assets), ("부채총계", 400), ("자본총계", 600))):
                cur.execute("INSERT INTO report_lines (corp_code, rcept_no, report_fiscal_year, "
                            "report_fiscal_period, statement, basis, label_raw, value_won, "
                            "row_order, col_index, table_seq) VALUES (%s,%s,%s,'FY','BS','consolidated',"
                            "%s,%s,%s,0,0)", (CORP, r, fy, lab, v, i))
            cur.execute("INSERT INTO download_tasks (rcept_no, status, file_path, file_type) "
                        "VALUES (%s, 'completed', %s, 'xml')", (r, str(xml)))
        # R_SIGN: dividends printed without parentheses; the DB followed the source
        sign_xml = xml.parent / "sign.xml"
        sign_xml.write_text(SIGN_XML, encoding="utf-8")
        cur.execute("INSERT INTO filings (rcept_no, corp_code, report_type, fiscal_year, "
                    "fiscal_period, is_amendment, filed_at, report_nm) VALUES "
                    "(%s, %s, 'annual', 2022, 'FY', false, '2023-03-01', '사업보고서')", (R_SIGN, CORP))
        for i, (lab, vals) in enumerate((("2022.01.01 (기초자본)", (100, 50)), ("배당금지급", (None, 7)),
                                         ("2022.12.31 (기말자본)", (100, 43)))):
            for col, v in enumerate(vals):
                if v is not None:
                    cur.execute("INSERT INTO report_lines (corp_code, rcept_no, report_fiscal_year, "
                                "report_fiscal_period, statement, basis, label_raw, value_won, "
                                "row_order, col_index, table_seq) VALUES (%s,%s,2022,'FY','SCE','separate',"
                                "%s,%s,%s,%s,0)", (CORP, R_SIGN, lab, v, i, col))
        cur.execute("INSERT INTO download_tasks (rcept_no, status, file_path, file_type) "
                    "VALUES (%s, 'completed', %s, 'xml')", (R_SIGN, str(sign_xml)))
    conn.commit()
    conn.close()
    engs = {"admin": _engine(None, "main"), "verify": _engine("tjf_verify", "camp_run:machine"),
            "model": _engine("tjf_verify", "camp_run")}
    yield engs
    for e in engs.values():
        e.dispose()
    _run("dropdb", "--if-exists", "--force", TEST_DB)


@pytest.fixture
def as_role(engines, monkeypatch):
    monkeypatch.setattr(runner, "usage_snapshot", lambda: (None, None))
    monkeypatch.setattr(runner, "_notify", lambda msg: None)
    monkeypatch.setattr(dz, "tg", lambda method, payload, timeout=20: {"message_id": 0})

    def _use(role: str):
        for mod in (ops, dz, runner, machine_pass):
            monkeypatch.setattr(mod, "engine", engines[role])
    return _use


def _sql(engines, sql, params=None):
    with engines["admin"].begin() as c:
        res = c.execute(text(sql), params or {})
        return res.fetchall() if res.returns_rows else None


def _kv(engines, key, value):
    _sql(engines, "INSERT INTO verification.kv (key, value, updated_at) VALUES (:k, :v, now()) "
         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", {"k": key, "v": value})


def test_gate_hides_unchecked_slots_from_the_model(engines, as_role):
    as_role("admin")
    ops.init_era("2015+")
    _kv(engines, "machine.gate", "on")
    _kv(engines, "machine.audit_pct", "0")
    as_role("model")
    assert ops.claim() is None                         # nothing machine-checked yet


def test_machine_passes_clean_and_leaves_mismatch_for_the_model(engines, as_role):
    as_role("verify")
    total = machine_pass.run(limit=10, log=lambda _m: None)
    assert total["slots"] == 3 and total["clean"] == 1 and total["mismatch"] == 1
    assert total["auto_issue"] == 1
    rows = dict(_sql(engines, "SELECT rcept_no, verdict FROM verification.machine_checks"))
    assert rows == {R_OK: "clean", R_BAD: "mismatch", R_SIGN: "mismatch"}
    st = dict(_sql(engines, "SELECT fiscal_year, status FROM verification.progress"))
    assert st == {2024: "passed", 2023: "pending", 2022: "has_issues"}
    iss = _sql(engines, "SELECT account_label, column_label, db_value, source_value, error_type, rule_id "
               "FROM verification.issues WHERE rcept_no = :r", {"r": R_SIGN})
    assert iss == [("배당금지급", "이익잉여금", 7, -7, "sign_flip", "R162")]
    who = _sql(engines, "SELECT verified_by, note FROM verification.progress_filings "
               "WHERE rcept_no = :r", {"r": R_OK})[0]
    assert who[0] == "camp_run:machine" and who[1].startswith("[machine ")
    # nothing left for the machine: a second run claims nothing
    assert machine_pass.run(limit=10, log=lambda _m: None)["slots"] == 0


def test_model_claims_the_mismatch_slot_and_sees_findings(engines, as_role):
    as_role("model")
    assert ops.claim() == SLOT_BAD
    f = ops.slot_detail(SLOT_BAD)["filings"][0]
    assert f["machine_verdict"] == "mismatch" and f["machine_current"]
    kinds = sorted(x["kind"] for x in f["machine_findings"])
    assert "value" in kinds
    ops.done(SLOT_BAD)


def test_reload_makes_the_check_stale_and_the_machine_rechecks(engines, as_role):
    # the fix side reloads R_BAD with the right value -> load_seq moves, check is stale
    _sql(engines, "UPDATE report_lines SET value_won = 1000 WHERE rcept_no = :r AND label_raw = '자산총계'",
         {"r": R_BAD})
    as_role("model")
    assert ops.claim() is None                         # stale check: machine first
    as_role("verify")
    total = machine_pass.run(limit=10, log=lambda _m: None)
    assert total["clean"] == 1
    assert dict(_sql(engines, "SELECT fiscal_year, status FROM verification.progress"))[2023] == "passed"
    assert ops.status()["machine"]["tool"] == machine_pass.mc.TOOL_VERSION


def test_audit_draw_keeps_a_clean_slot_for_the_model(engines, as_role):
    _kv(engines, "machine.audit_pct", "100")
    _sql(engines, "UPDATE report_lines SET value_won = 1001 WHERE rcept_no = :r AND label_raw = '자산총계'",
         {"r": R_OK})
    _sql(engines, "UPDATE report_lines SET value_won = 1000 WHERE rcept_no = :r AND label_raw = '자산총계'",
         {"r": R_OK})
    # identical content after the round trip: load_seq may or may not move - force a re-check
    _sql(engines, "DELETE FROM verification.machine_checks WHERE rcept_no = :r", {"r": R_OK})
    _sql(engines, "UPDATE verification.progress_filings SET status = 'pending' WHERE rcept_no = :r", {"r": R_OK})
    _sql(engines, "SELECT verification.refresh_slot(:c, 2024, 'FY')", {"c": CORP})
    as_role("verify")
    total = machine_pass.run(limit=10, log=lambda _m: None)
    assert total["audit"] == 1 and total["clean"] == 0
    assert _sql(engines, "SELECT audit FROM verification.machine_checks WHERE rcept_no = :r",
                {"r": R_OK})[0][0] is True
    as_role("model")
    assert ops.claim() == SLOT_OK
    ops.done(SLOT_OK)
