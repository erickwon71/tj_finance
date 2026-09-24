"""verification ops/decisions/runner against a throw-away DB, with real role switching.

Engines are swapped per role by monkeypatching the module-level `engine` the functions use,
so the same code path the CLI takes is exercised as tjf_verify / tjf_fix / admin.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

psycopg2 = pytest.importorskip("psycopg2")
from sqlalchemy import create_engine, event, text  # noqa: E402

from fin2.verification import decisions as dz  # noqa: E402
from fin2.verification import ops, runner  # noqa: E402
from fin2.verification.ops import Slot, VqError  # noqa: E402
from fin2.verification.schema import SCHEMA_SQL  # noqa: E402

TEST_DB = "tjf_vtest_ops"
CORP = "99000002"
R1, R2 = "29990101000011", "29990301000012"
SLOT = Slot(CORP, 2024, "FY")
TABLES = ("corporations", "filings", "report_lines", "stock_prices",
          "report_shares_outstanding", "download_tasks")


def _run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _engine(user: str | None, actor: str):
    url = f"postgresql://{user + '@' if user else ''}/{TEST_DB}"
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _ident(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("SELECT set_config('verification.actor', %s, false)", (actor,))
        cur.execute("SELECT set_config('verification.parser_commit', 'c0ffee', false)")
        dbapi_conn.commit()
        cur.close()
    return eng


@pytest.fixture(scope="module")
def engines():
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
    # The live report_lines carries the verification triggers; they are recreated by
    # schema.sql below, and would fail here because their functions do not exist yet.
    dump = "\n".join(l for l in dump.splitlines() if "verification." not in l)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", TEST_DB], input=dump,
                   check=True, capture_output=True, text=True)
    conn = psycopg2.connect(dbname=TEST_DB)
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute("INSERT INTO corporations (corp_code, corp_name, market, stock_code, "
                    "is_active, coverage_class) VALUES (%s, 'TESTCO', 'KOSPI', '123450', true, "
                    "'periodic')", (CORP,))
        for r, amend, day in ((R1, False, "2025-03-01"), (R2, True, "2025-04-01")):
            cur.execute("INSERT INTO filings (rcept_no, corp_code, report_type, fiscal_year, "
                        "fiscal_period, is_amendment, filed_at, report_nm) VALUES "
                        "(%s, %s, 'annual', 2024, 'FY', %s, %s, '사업보고서')",
                        (r, CORP, amend, day))
            for i, (st, b, lab, v) in enumerate((("BS", "consolidated", "자산총계", 100),
                                                  ("IS", "separate", "매출액", 50))):
                cur.execute("INSERT INTO report_lines (corp_code, rcept_no, report_fiscal_year, "
                            "report_fiscal_period, statement, basis, label_raw, value_won, "
                            "row_order, col_index) VALUES (%s,%s,2024,'FY',%s,%s,%s,%s,%s,0)",
                            (CORP, r, st, b, lab, v, i))
    conn.commit()
    conn.close()
    engs = {"admin": _engine(None, "main"), "verify": _engine("tjf_verify", "camp_run"),
            "fix": _engine("tjf_fix", "camp_err_review")}
    yield engs
    for e in engs.values():
        e.dispose()
    _run("dropdb", "--if-exists", "--force", TEST_DB)


@pytest.fixture
def as_role(engines, monkeypatch):
    # The usage probe calls the network; runner bookkeeping must not depend on it in tests.
    monkeypatch.setattr(runner, "usage_snapshot", lambda: (None, None))
    # Never reach the real Telegram from a test (2026-09-24: the usage-limit test did, twice,
    # because only the stop test patched _notify and the stop condition carried over).
    monkeypatch.setattr(runner, "_notify", lambda msg: None)
    monkeypatch.setattr(dz, "tg", lambda method, payload, timeout=20: {"message_id": 0})

    def _use(role: str):
        for mod in (ops, dz, runner):
            monkeypatch.setattr(mod, "engine", engines[role])
    return _use


def _admin_sql(engines, sql, params=None):
    with engines["admin"].begin() as c:
        res = c.execute(text(sql), params or {})
        return res.fetchall() if res.returns_rows else None


def test_init_creates_slot_with_both_filings(engines, as_role):
    as_role("admin")
    res = ops.init_era("2015+")
    assert res["new_filings"] == 2
    assert ops.init_era("2015+")["new_filings"] == 0          # idempotent
    rows = _admin_sql(engines, "SELECT rcept_no, seq_in_slot, is_amendment FROM "
                      "verification.progress_filings WHERE corp_code = :c ORDER BY seq_in_slot",
                      {"c": CORP})
    assert rows == [(R1, 1, False), (R2, 2, True)]


def test_fix_role_cannot_claim(as_role):
    as_role("fix")
    with pytest.raises(VqError):
        ops.claim()


def test_claim_show_and_pass_gate(engines, as_role):
    as_role("verify")
    assert ops.claim() == SLOT
    d = ops.slot_detail(SLOT)
    f1 = next(f for f in d["filings"] if f["rcept_no"] == R1)
    assert f1["scope_rows"] == {"sep-is": 1, "con-bs": 1}
    # The amendment is byte-identical to the original in both scopes.
    f2 = next(f for f in d["filings"] if f["rcept_no"] == R2)
    assert f2["identical_to_earlier"] == {R1: ["con-bs", "sep-is"]}

    with pytest.raises(VqError, match="실제 적재 scope"):
        ops.pass_filing(R1, ["con-bs"], "partial")            # sep-is missing
    with pytest.raises(VqError, match="실제 적재 scope"):
        ops.pass_filing(R1, ["con-bs", "sep-is", "con-cf"], "extra")
    ops.pass_filing(R1, ["con-bs", "sep-is"], "full 8-scope comparison")


def test_reload_during_review_rejects_verdict(engines, as_role):
    # admin (daily pipeline) changes R2 while the reviewer holds the lease
    _admin_sql(engines, "UPDATE report_lines SET value_won = 51 WHERE rcept_no = :r "
               "AND statement = 'IS'", {"r": R2})
    as_role("verify")
    with pytest.raises(VqError, match="재적재"):
        ops.pass_filing(R2, ["con-bs", "sep-is"], None)
    d = ops.slot_detail(SLOT)
    f2 = next(f for f in d["filings"] if f["rcept_no"] == R2)
    assert f2["identical_to_earlier"] == {R1: ["con-bs"]}


def test_issue_then_done_gives_has_issues(engines, as_role):
    as_role("verify")
    # re-claim own slot refreshes claim_load_seq to the new content
    assert ops.claim(SLOT) == SLOT
    ids = ops.add_issues(R2, [{"basis": "separate", "statement": "IS", "account_label": "매출액",
                               "db_value": 51, "source_value": 50, "source_value_raw": "50",
                               "source_unit": "원", "error_type": "value_mismatch",
                               "evidence": "원문 50, DB 51"}])
    res = ops.done()
    assert res["status"] == "has_issues" and res["outcome"] == "has_issues"
    assert ops.own_slot() is None
    test_issue_then_done_gives_has_issues.issue_id = ids[0]


def test_fix_batch_cycle_and_recheck(engines, as_role, monkeypatch):
    issue_id = test_issue_then_done_gives_has_issues.issue_id
    as_role("fix")
    q = ops.fix_queue()
    assert q["groups"][0]["error_type"] == "value_mismatch"
    b = ops.batch_new("value_mismatch", "test batch", None, "R999")
    assert b["issues"] == 1

    monkeypatch.setattr(ops, "require_clean_pushed_head", lambda: "feedbee")
    res = ops.batch_mark_fixed(b["batch_id"])
    assert res["fixed"] == [] and res["not_fixed"]           # no reload yet → refused
    with engines["fix"].begin() as c:                          # the "reload" of the fix
        c.execute(text("UPDATE report_lines SET value_won = 50 WHERE rcept_no = :r "
                       "AND statement = 'IS'"), {"r": R2})
    res = ops.batch_mark_fixed(b["batch_id"])
    assert res["fixed"] == [issue_id]

    as_role("verify")
    rows = ops.recheck_list(SLOT)
    assert rows[0]["db_value_now"] == [50]
    # claim prefers the slot with a fixed issue waiting
    assert ops.claim() == SLOT
    with pytest.raises(Exception):
        ops.transition(issue_id, "reopened", None)             # evidence required
    ops.transition(issue_id, "closed", "원문 50 = DB 50 재확인")
    d = ops.slot_detail(SLOT)
    f2 = next(f for f in d["filings"] if f["rcept_no"] == R2)
    assert f2["status"] == "pending"
    ops.pass_filing(R2, ["con-bs", "sep-is"], "재대조 완료")
    assert ops.done()["status"] == "passed"


def test_passed_slot_demoted_by_fix_reload_with_changed_scope(engines, as_role):
    as_role("fix")
    with engines["fix"].begin() as c:
        c.execute(text("UPDATE report_lines SET value_won = 101 WHERE rcept_no = :r "
                       "AND statement = 'BS'"), {"r": R1})
    as_role("verify")
    d = ops.slot_detail(SLOT)
    assert d["slot"]["status"] == "pending"
    f1 = next(f for f in d["filings"] if f["rcept_no"] == R1)
    assert f1["status"] == "pending" and f1["changed_since_verified"] == ["con-bs"]


# ─────────────────────────────── decisions ───────────────────────────────
OPTS = [{"key": "A", "label": "지금 실행", "consequence": "2시간 재적재"},
        {"key": "B", "label": "보류", "consequence": "배치 주차"}]
DAY = datetime(2026, 9, 24, 14, 0)
NIGHT = datetime(2026, 9, 24, 23, 30)


def test_decision_gate(as_role):
    as_role("fix")
    with pytest.raises(VqError, match="스스로 결정"):
        dz.ask(category="progress", question="q", options=OPTS, recommended="A",
               dedupe_key="k0", now=DAY, send=False)
    with pytest.raises(VqError, match="2~4"):
        dz.ask(category="policy", question="q", options=OPTS[:1], recommended="A",
               dedupe_key="k0", now=DAY, send=False)
    with pytest.raises(VqError, match="권장안"):
        dz.ask(category="policy", question="q", options=OPTS, recommended="Z",
               dedupe_key="k0", now=DAY, send=False)
    with pytest.raises(VqError, match="consequence"):
        dz.ask(category="policy", question="q",
               options=[{"key": "A", "label": "x", "consequence": ""}, OPTS[1]],
               recommended="A", dedupe_key="k0", now=DAY, send=False)
    with pytest.raises(VqError, match="야간"):
        dz.ask(category="policy", question="q", options=OPTS, recommended="A",
               dedupe_key="k0", now=NIGHT, send=False)
    as_role("verify")
    with pytest.raises(VqError):
        dz.ask(category="policy", question="q", options=OPTS, recommended="A",
               dedupe_key="k0", now=DAY, send=False)


def test_decision_dedupe_cap_answer_and_expiry(engines, as_role):
    as_role("fix")
    a = dz.ask(category="irreversible", question="R999 백필?", options=OPTS, recommended="A",
               dedupe_key="k1", now=NIGHT, send=False)
    assert a["reason"].startswith("야간")                     # created, held for the digest
    assert dz.ask(category="irreversible", question="R999 백필?", options=OPTS,
                  recommended="A", dedupe_key="k1", now=NIGHT, send=False)["decision_id"] == a["decision_id"]
    b = dz.ask(category="policy", question="정책?", options=OPTS, recommended="B",
               dedupe_key="k2", now=DAY, send=False)
    dz.ask(category="scope", question="범위?", options=OPTS, recommended="A",
           dedupe_key="k3", now=DAY, send=False)
    with pytest.raises(VqError, match="3건"):
        dz.ask(category="scope", question="넷째", options=OPTS, recommended="A",
               dedupe_key="k4", now=DAY, send=False)

    with engines["fix"].connect() as c:
        nonce = c.execute(text("SELECT nonce FROM verification.decisions WHERE decision_id=:i"),
                          {"i": b["decision_id"]}).scalar()
    assert dz.record_answer(b["decision_id"], key="A", via="telegram", nonce="bad")[0] is False
    assert dz.record_answer(b["decision_id"], key="A", via="telegram", nonce=nonce)[0] is True
    assert dz.record_answer(b["decision_id"], key="B", via="telegram", nonce=nonce)[0] is False

    # Force both remaining pending ones past expiry.
    _admin_sql(engines, "UPDATE verification.decisions SET expires_at = now() - interval '1 min' "
               "WHERE status = 'pending'")
    expired = dz.expire_due()
    with engines["fix"].connect() as c:
        rows = dict(c.execute(text("SELECT category, status FROM verification.decisions "
                                   "WHERE dedupe_key IN ('k1', 'k3')")).fetchall())
    assert rows == {"irreversible": "pending", "scope": "expired"}   # irreversible never auto
    assert len(expired) == 1


def test_bot_ignores_foreign_chat_and_records_tap(engines, as_role, monkeypatch):
    as_role("admin")
    sent = []
    monkeypatch.setattr(dz, "tg", lambda method, payload, timeout=20: sent.append(method) or {})
    with engines["admin"].connect() as c:
        d = c.execute(text("SELECT decision_id, nonce FROM verification.decisions "
                           "WHERE status = 'pending' AND category = 'irreversible'")).fetchone()
    upd = {"update_id": 1, "callback_query": {
        "id": "x", "from": {"id": 666}, "message": {"chat": {"id": 666}},
        "data": f"d:{d[0]}:A:{d[1]}"}}
    assert dz.handle_update(upd, "111").startswith("ignored")
    upd["callback_query"]["from"]["id"] = 111
    upd["callback_query"]["message"]["chat"]["id"] = 111
    line = dz.handle_update(upd, "111")
    assert "A 지금 실행" in line
    with engines["admin"].connect() as c:
        assert c.execute(text("SELECT status, answer_key, answered_via FROM verification.decisions "
                              "WHERE decision_id = :i"), {"i": d[0]}).fetchone() == (
            "answered", "A", "telegram")


# ─────────────────────────────── runner ───────────────────────────────
def _fake_log(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_runner_classifies_incomplete_and_stops_after_three(engines, as_role, tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(runner, "_notify", lambda msg: None)
    as_role("verify")
    outcomes = []
    for i in range(3):
        slot = ops.claim(SLOT) if ops.own_slot() is None else ops.own_slot()
        run_id = runner.start(slot, "sonnet")
        log = _fake_log(tmp_path, f"r{i}.json", {"type": "result", "is_error": False,
                                                 "num_turns": 5, "result": "stopped early",
                                                 "usage": {"input_tokens": 10,
                                                           "output_tokens": 3}})
        res = runner.finish(run_id, log, 0)
        outcomes.append(res["outcome"])
        if res["outcome"] == "blocked":
            break
    assert outcomes[0] == "incomplete"
    assert res["stop"] is True
    assert ops.slot_status(SLOT) == "blocked"


def test_runner_usage_limit_has_no_retry_penalty(engines, as_role, tmp_path):
    _admin_sql(engines, "UPDATE verification.progress SET status='pending', retry_count=0 "
               "WHERE corp_code=:c", {"c": CORP})
    as_role("verify")
    slot = ops.claim(SLOT)
    run_id = runner.start(slot, "sonnet")
    log = _fake_log(tmp_path, "lim.json", {"type": "result", "is_error": True,
                                           "result": "Claude AI usage limit reached|4102444800"})
    res = runner.finish(run_id, log, 1)
    assert res["outcome"] == "usage_limit" and res["sleep_until"].startswith("2100-01-01")
    with engines["admin"].connect() as c:
        assert c.execute(text("SELECT status, retry_count FROM verification.progress "
                              "WHERE corp_code=:c"), {"c": CORP}).fetchone() == ("pending", 0)
    assert runner.budget_state()["wait_seconds"] > 0
