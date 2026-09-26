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
import os
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
# 2026-09-26: ~14 parallel Bash calls in one turn tripped dontAsk mode into denying every
# further Bash call (including read-only `vq.py show`) for the rest of that run — the model
# then can't even call `vq.py done`. Not a data problem, so it must not burn a retry or count
# toward the consecutive-failure stop (docs/qa/handoff_2026-09-26_full_automation.md §2).
# ★The model's own summary paraphrases the denial instead of always quoting the literal tool
# error, in wording that keeps drifting (English, Korean, "don't ask mode" mentioned or not —
# runs 393/394/407/408/409 same day). A text regex chases an open-ended paraphrase space and
# will keep missing new phrasings. The reliable signal is the *structured* `permission_denials`
# array Claude Code itself attaches to the result JSON (see `finish()`) — this regex is now
# only a fallback for the rare case that field is empty but the text still names the error.
_BASH_DENIED_RE = re.compile(r"permission to use bash has been denied|don't ask mode", re.I)


def _kv(conn, key: str) -> str:
    v = conn.execute(text("SELECT value FROM verification.kv WHERE key = :k"),
                     {"k": key}).scalar()
    return v if v is not None else DEFAULTS.get(key, "")


_USAGE_PROBE = Path.home() / ".claude/plugins/cache/claude-dashboard/claude-dashboard"


def usage_probe() -> dict:
    """Claude account usage from the installed claude-dashboard plugin (latest version):
    {fiveHourPercent, sevenDayPercent, fiveHourReset, sevenDayReset}, or {} if unavailable."""
    try:
        scripts = sorted(_USAGE_PROBE.glob("*/dist/check-usage.js"),
                         key=lambda p: [int(x) if x.isdigit() else x
                                        for x in re.split(r"[.]", p.parts[-3])])
        if not scripts:
            return {}
        out = subprocess.run(["node", str(scripts[-1]), "--json"], capture_output=True,
                             text=True, timeout=30)
        c = (json.loads(out.stdout) or {}).get("claude") or {}
        return {} if c.get("error") else c
    except Exception:  # noqa: BLE001 — bookkeeping only, never block a run
        return {}


def usage_snapshot() -> tuple[float | None, float | None]:
    """(5-hour %, 7-day %) of the Claude account, or (None, None) if the probe is missing."""
    c = usage_probe()
    return c.get("fiveHourPercent"), c.get("sevenDayPercent")


def pace_wait(c: dict, *, max_5h: float, reserve_7d: float, safety_7d: float,
              now=None) -> tuple[int, str | None]:
    """Seconds to wait under measured-usage pacing (Max x5 tuning, design §11), and why.

    - 5-hour window: at or above max_5h percent, wait for its reset (the rest of the window
      belongs to the interactive / fix sessions).
    - Weekly: keep a reserve for the fix + interactive sessions proportional to the time left
      in the week: stop at `100 - reserve_7d x remaining_fraction - safety_7d`. Early in the
      week the runner stops well before the limit; near the reset the ceiling rises toward
      100 - safety. Unlike an elapsed-time pace line this does not idle the runner for days
      because of usage that happened earlier in the week (pilot day: 58% used at 30% elapsed).
    Missing data never blocks (the usage_limit handling is the backstop).
    """
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)

    def _ts(v):
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    five, seven = c.get("fiveHourPercent"), c.get("sevenDayPercent")
    five_reset, seven_reset = _ts(c.get("fiveHourReset")), _ts(c.get("sevenDayReset"))
    if five is not None and five >= max_5h and five_reset:
        return max(60, int((five_reset - now).total_seconds())), f"5h {five}% >= {max_5h}%"
    if seven is not None and seven_reset:
        remaining = max(0.0, (seven_reset - now).total_seconds()) / timedelta(days=7).total_seconds()
        ceiling = 100 - reserve_7d * min(1.0, remaining) - safety_7d
        if seven >= ceiling:
            return 1800, f"7d {seven}% >= ceiling {ceiling:.1f}%"
    return 0, None


def start(slot: Slot, model: str | None) -> int:
    five, seven = usage_snapshot()
    with _Tx() as conn:
        return conn.execute(text("""
            INSERT INTO verification.runner_runs
                (worktree, corp_code, fiscal_year, fiscal_period, model, git_head,
                 usage_5h_start, usage_7d_start)
            VALUES (:w, :c, :y, :p, :m, :g, :u5, :u7) RETURNING run_id"""),
            {"w": worktree_name(), **slot.params(), "m": model,
             "g": parser_commit(), "u5": five, "u7": seven}).scalar_one()


def budget_state() -> dict:
    """How long the loop must wait before the next run (0 = go)."""
    with engine.connect() as conn:
        per_window = int(_kv(conn, "runner.slots_per_window") or 12)
        weekly = _kv(conn, "runner.weekly_slots")
        runs_5h, oldest_5h = conn.execute(text("""
            SELECT count(*), min(started_at) FROM verification.runner_runs
            WHERE started_at > now() - interval '5 hours'
              AND coalesce(outcome, '') NOT IN ('usage_limit', 'tool_denied')""")).fetchone()
        wait = 0
        if runs_5h >= per_window:
            wait = conn.execute(text(
                "SELECT greatest(0, extract(epoch FROM :t + interval '5 hours' - now()))::bigint"),
                {"t": oldest_5h}).scalar_one()
        runs_7d = conn.execute(text("""
            SELECT count(*) FROM verification.runner_runs
            WHERE started_at > now() - interval '7 days'
              AND coalesce(outcome, '') NOT IN ('usage_limit', 'tool_denied')""")).scalar_one()
        if weekly and runs_7d >= int(weekly):
            wait = max(wait, 3600)
        limited_until = conn.execute(text("""
            SELECT value FROM verification.kv WHERE key = 'runner.limited_until'""")).scalar()
        if limited_until:
            wait = max(wait, conn.execute(text(
                "SELECT greatest(0, extract(epoch FROM CAST(:t AS timestamptz) - now()))::bigint"),
                {"t": limited_until}).scalar_one())
        pace = _kv(conn, "runner.pace_mode") == "on"
        max_5h = float(_kv(conn, "runner.max_5h_pct") or 70)
        reserve_7d = float(_kv(conn, "runner.reserve_7d_pct") or 40)
        safety_7d = float(_kv(conn, "runner.safety_7d_pct") or 5)
        # Pilot: stop by itself after N measured runs (runs with a usage snapshot), so the
        # un-throttled pilot cannot drain the weekly limit unnoticed.
        target = _kv(conn, "runner.stop_after_measured_runs")
        measured = conn.execute(text("""
            SELECT count(*) FROM verification.runner_runs
            WHERE usage_7d_start IS NOT NULL AND ended_at IS NOT NULL""")).scalar_one()
    stop = bool(target) and measured >= int(target)
    pace_reason = None
    if pace and not stop:
        pw, pace_reason = pace_wait(usage_probe(), max_5h=max_5h, reserve_7d=reserve_7d,
                                    safety_7d=safety_7d)
        wait = max(wait, pw)
    return {"wait_seconds": int(wait), "pace": pace, "pace_reason": pace_reason,
            "runs_5h": runs_5h, "slots_per_window": per_window,
            "runs_7d": runs_7d, "weekly_slots": weekly or None,
            "measured_runs": measured, "stop_after": int(target) if target else None,
            "stop": stop}


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
    # Belt and braces: a test run must never message the user.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if NOTIFY.exists():
        rc = subprocess.run([str(NOTIFY), msg[:190]], capture_output=True, timeout=30).returncode
        # Same log the Notification hook writes, so "which process sent this?" is answerable.
        from datetime import datetime
        with (NOTIFY.parent / "sent.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%m-%d %H:%M:%S}  runner    {'sent' if rc == 0 else 'queued'} "
                     f"{msg[:190]}\n")


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
    elif (data.get("permission_denials") or _BASH_DENIED_RE.search(result_text)) \
            and status == "in_progress":
        outcome = "tool_denied"
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
    if outcome == "tool_denied":
        # Not the slot's fault either: release without a retry penalty, no back-off needed
        # (each `claude -p` run starts a fresh process, so the next run is unaffected).
        ops.release(slot, failed=False, note=f"runner run {run_id}: tool_denied")
    elif outcome == "usage_limit":
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

    five, seven = usage_snapshot()
    with _Tx() as conn:
        conn.execute(text("""
            UPDATE verification.runner_runs
               SET ended_at = now(), exit_code = :x, outcome = :o, log_path = :l,
                   num_turns = :t, input_tokens = :i, output_tokens = :ot, cost_usd = :c,
                   usage_5h_end = :u5, usage_7d_end = :u7
             WHERE run_id = :r"""),
            {"r": run_id, "x": exit_code, "o": outcome, "l": str(log), "u5": five, "u7": seven,
             "t": data.get("num_turns"),
             "i": (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
                  + (usage.get("cache_creation_input_tokens") or 0) or None,
             "ot": usage.get("output_tokens"), "c": data.get("total_cost_usd")})
        last = [r[0] for r in conn.execute(text("""
            SELECT outcome FROM verification.runner_runs
            WHERE worktree = :w AND outcome IS NOT NULL
              AND outcome NOT IN ('usage_limit', 'tool_denied')
            ORDER BY run_id DESC LIMIT :n"""),
            {"w": run["worktree"], "n": STOP_AFTER_CONSECUTIVE_FAILS}).fetchall()]

    stop = (len(last) == STOP_AFTER_CONSECUTIVE_FAILS
            and all(o in FAIL_OUTCOMES for o in last))
    if stop:
        _notify(f"[verify 러너 정지] 연속 {STOP_AFTER_CONSECUTIVE_FAILS}회 실패({','.join(last)}) "
                f"— 마지막 {slot} run {run_id}. 로그 {log.name}")
    return {"run_id": run_id, "slot": str(slot), "outcome": outcome, "stop": stop,
            "sleep_until": sleep_until.isoformat() if sleep_until else None}
