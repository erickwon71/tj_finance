"""Bookkeeping for scripts/verify_runner.sh (one `claude -p` run = one slot).

The shell loop owns process control (timeout, sleep, STOP file); this module owns every
decision that needs the DB: what the run achieved, whether to retry, whether to back off
for the usage budget, whether to stop the loop.

Budget knobs live in verification.kv so the pilot can tune them without a code change:
  runner.slots_per_window  (default 12)  runs per rolling 5-hour window
  runner.weekly_slots      (default none) runs per rolling 7 days, set after the pilot
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from sqlalchemy import text

from collector.db import engine
from fin2.verification import ops
from fin2.verification.ops import Slot, _Tx
from fin2.verification.session_info import parser_commit, worktree_name

DEFAULTS = {"runner.slots_per_window": "12", "runner.weekly_slots": ""}
FAIL_OUTCOMES = ("error", "timeout", "incomplete", "blocked")
STOP_AFTER_CONSECUTIVE_FAILS = 3
NOTIFY = Path.home() / ".claude" / "notify" / "telegram.sh"
_LIMIT_RE = re.compile(r"(usage limit|limit reached|rate limit|resets? )", re.I)
_EPOCH_RE = re.compile(r"\|(\d{10})\b")


def _kv(conn, key: str) -> str:
    v = conn.execute(text("SELECT value FROM verification.kv WHERE key = :k"),
                     {"k": key}).scalar()
    return v if v is not None else DEFAULTS.get(key, "")


def start(slot: Slot, model: str | None) -> int:
    with _Tx() as conn:
        return conn.execute(text("""
            INSERT INTO verification.runner_runs
                (worktree, corp_code, fiscal_year, fiscal_period, model, git_head)
            VALUES (:w, :c, :y, :p, :m, :g) RETURNING run_id"""),
            {"w": worktree_name(), **slot.params(), "m": model,
             "g": parser_commit()}).scalar_one()


def budget_state() -> dict:
    """How long the loop must wait before the next run (0 = go)."""
    with engine.connect() as conn:
        per_window = int(_kv(conn, "runner.slots_per_window") or 12)
        weekly = _kv(conn, "runner.weekly_slots")
        runs_5h, oldest_5h = conn.execute(text("""
            SELECT count(*), min(started_at) FROM verification.runner_runs
            WHERE started_at > now() - interval '5 hours'
              AND coalesce(outcome, '') <> 'usage_limit'""")).fetchone()
        wait = 0
        if runs_5h >= per_window:
            wait = conn.execute(text(
                "SELECT greatest(0, extract(epoch FROM :t + interval '5 hours' - now()))::bigint"),
                {"t": oldest_5h}).scalar_one()
        runs_7d = conn.execute(text("""
            SELECT count(*) FROM verification.runner_runs
            WHERE started_at > now() - interval '7 days'
              AND coalesce(outcome, '') <> 'usage_limit'""")).scalar_one()
        if weekly and runs_7d >= int(weekly):
            wait = max(wait, 3600)
        limited_until = conn.execute(text("""
            SELECT value FROM verification.kv WHERE key = 'runner.limited_until'""")).scalar()
        if limited_until:
            wait = max(wait, conn.execute(text(
                "SELECT greatest(0, extract(epoch FROM CAST(:t AS timestamptz) - now()))::bigint"),
                {"t": limited_until}).scalar_one())
    return {"wait_seconds": int(wait), "runs_5h": runs_5h, "slots_per_window": per_window,
            "runs_7d": runs_7d, "weekly_slots": weekly or None}


def _parse_log(log: Path) -> dict:
    try:
        raw = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"_raw": ""}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"_raw": raw[-4000:]}
    except json.JSONDecodeError:
        return {"_raw": raw[-4000:]}


def _notify(msg: str) -> None:
    if NOTIFY.exists():
        subprocess.run([str(NOTIFY), msg[:190]], capture_output=True, timeout=30)


def finish(run_id: int, log: Path, exit_code: int) -> dict:
    """Classify a finished run, repair slot state if the session did not, decide on stop."""
    with engine.connect() as conn:
        run = conn.execute(text("SELECT * FROM verification.runner_runs WHERE run_id = :r"),
                           {"r": run_id}).mappings().one()
    slot = Slot(run["corp_code"], run["fiscal_year"], run["fiscal_period"])
    data = _parse_log(log)
    result_text = str(data.get("result") or data.get("_raw") or "")
    usage = data.get("usage") or {}
    status = ops.slot_status(slot)

    if exit_code == 124:
        outcome = "timeout"
    elif _LIMIT_RE.search(result_text) and data.get("is_error", True) and status == "in_progress":
        outcome = "usage_limit"
    elif status == "passed":
        outcome = "passed"
    elif status == "has_issues":
        outcome = "has_issues"
    elif status == "blocked":
        outcome = "blocked"
    elif exit_code != 0 or data.get("is_error"):
        outcome = "error"
    else:
        outcome = "incomplete"

    sleep_until = None
    if outcome == "usage_limit":
        # Not the slot's fault: release without a retry penalty and back off.
        ops.release(slot, failed=False, note=None)
        m = _EPOCH_RE.search(result_text)
        with _Tx() as conn:
            sleep_until = conn.execute(text(
                "SELECT CASE WHEN CAST(:e AS bigint) IS NOT NULL THEN to_timestamp(CAST(:e AS bigint)) "
                "ELSE now() + interval '30 minutes' END"),
                {"e": m.group(1) if m else None}).scalar_one()
            conn.execute(text("""
                INSERT INTO verification.kv (key, value, updated_at)
                VALUES ('runner.limited_until', :v, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""),
                {"v": sleep_until.isoformat()})
    elif outcome in ("timeout", "error", "incomplete"):
        # The session did not finish the slot: count a retry (blocked after MAX_RETRIES).
        if status == "in_progress":
            res = ops.release(slot, failed=True, note=f"runner run {run_id}: {outcome}")
        else:
            with _Tx(evidence=f"runner run {run_id}: {outcome}") as conn:
                res = {"status": conn.execute(text("""
                    UPDATE verification.progress
                       SET retry_count = retry_count + 1,
                           status = CASE WHEN retry_count + 1 >= :mx AND status = 'pending'
                                         THEN 'blocked' ELSE status END,
                           updated_at = now()
                     WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p
                    RETURNING status"""), {**slot.params(), "mx": ops.MAX_RETRIES}).scalar()}
        if res.get("status") == "blocked":
            outcome = "blocked"

    with _Tx() as conn:
        conn.execute(text("""
            UPDATE verification.runner_runs
               SET ended_at = now(), exit_code = :x, outcome = :o, log_path = :l,
                   num_turns = :t, input_tokens = :i, output_tokens = :ot, cost_usd = :c
             WHERE run_id = :r"""),
            {"r": run_id, "x": exit_code, "o": outcome, "l": str(log),
             "t": data.get("num_turns"),
             "i": (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
                  + (usage.get("cache_creation_input_tokens") or 0) or None,
             "ot": usage.get("output_tokens"), "c": data.get("total_cost_usd")})
        last = [r[0] for r in conn.execute(text("""
            SELECT outcome FROM verification.runner_runs
            WHERE worktree = :w AND outcome IS NOT NULL AND outcome <> 'usage_limit'
            ORDER BY run_id DESC LIMIT :n"""),
            {"w": run["worktree"], "n": STOP_AFTER_CONSECUTIVE_FAILS}).fetchall()]

    stop = (len(last) == STOP_AFTER_CONSECUTIVE_FAILS
            and all(o in FAIL_OUTCOMES for o in last))
    if stop:
        _notify(f"[verify 러너 정지] 연속 {STOP_AFTER_CONSECUTIVE_FAILS}회 실패({','.join(last)}) "
                f"— 마지막 {slot} run {run_id}. 로그 {log.name}")
    return {"run_id": run_id, "slot": str(slot), "outcome": outcome, "stop": stop,
            "sleep_until": sleep_until.isoformat() if sleep_until else None}
