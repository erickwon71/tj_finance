"""User decisions over Telegram: ask with inline buttons, record the tap, expire safely.

Why this exists: the fix worktree sometimes needs the user's call (irreversible actions,
parsing policy, scope, ambiguous source). The user is often away from the terminal, so the
question goes to Telegram with buttons, and the answer lands in `verification.decisions`,
where the next session reads it (fix-queue lists answered decisions first).

Noise control is enforced HERE, in code, not by convention (design §2.7):
  - only 4 categories may ask at all; anything else must be decided by the session itself
  - 2-4 options, a recommendation and a one-line consequence per option are mandatory
  - same dedupe_key while pending -> no new message
  - at most MAX_PENDING open questions; at most DAILY_SEND_CAP immediate sends per day
  - 22:00-08:00: only `irreversible` may be created, and it is sent by the 08:00 digest
  - expiry never auto-applies an `irreversible` answer

The bot token is read from ~/.claude/notify/telegram.env and never logged.
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from collector.db import engine
from fin2.verification.ops import VqError, _require, _Tx

CATEGORIES = ("irreversible", "policy", "scope", "source_ambiguity")
MAX_PENDING = 3
DAILY_SEND_CAP = 5
QUIET_START, QUIET_END = 22, 8
ENV_FILE = Path.home() / ".claude" / "notify" / "telegram.env"
API = "https://api.telegram.org/bot{token}/{method}"


# ─────────────────────────────── Telegram transport ───────────────────────────────
def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class TelegramError(RuntimeError):
    pass


def tg(method: str, payload: dict, timeout: int = 20) -> dict:
    """Call the Bot API. Exceptions are re-raised WITHOUT the URL (it contains the token)."""
    import os

    import requests

    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise TelegramError(f"{method}: blocked under pytest")
    env = _env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("telegram.env 에 TELEGRAM_BOT_TOKEN 없음")
    try:
        r = requests.post(API.format(token=token, method=method), json=payload, timeout=timeout)
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise TelegramError(f"{method}: {type(exc).__name__}") from None
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
    return data["result"]


def chat_id() -> str:
    cid = _env().get("TELEGRAM_CHAT_ID")
    if not cid:
        raise TelegramError("telegram.env 에 TELEGRAM_CHAT_ID 없음 — link_chat.sh 먼저")
    return cid


# ─────────────────────────────── formatting ───────────────────────────────
def render(d: dict) -> str:
    lines = [f"[판단 #{d['decision_id']} · {d['category']}] {d['question']}"]
    for o in d["options"]:
        star = "★" if o["key"] == d["recommended"] else " "
        lines.append(f" {star}{o['key']} {o['label']} — {o['consequence']}")
    if d["category"] == "irreversible" or not d["apply_default_on_expiry"]:
        tail = "만료돼도 자동 실행 안 함"
    else:
        tail = f"만료 시 권장안 {d['recommended']} 적용"
    lines.append(f"(답장으로 다른 지시 가능 · {d['expires_at']:%m-%d %H:%M} 만료, {tail})")
    return "\n".join(lines)


def _keyboard(d: dict) -> dict:
    rows = []
    for o in d["options"]:
        star = "★" if o["key"] == d["recommended"] else ""
        rows.append([{"text": f"{star}{o['key']} {o['label']}"[:40],
                      "callback_data": f"d:{d['decision_id']}:{o['key']}:{d['nonce']}"}])
    return {"inline_keyboard": rows}


def _is_quiet(now: datetime) -> bool:
    return now.hour >= QUIET_START or now.hour < QUIET_END


def _load(conn, decision_id: int) -> dict:
    row = conn.execute(text("SELECT * FROM verification.decisions WHERE decision_id = :i"),
                       {"i": decision_id}).mappings().fetchone()
    if row is None:
        raise VqError(f"판단 #{decision_id} 없음")
    return dict(row)


def _send(conn, d: dict) -> None:
    res = tg("sendMessage", {"chat_id": chat_id(), "text": render(d),
                             "reply_markup": _keyboard(d),
                             "disable_web_page_preview": True})
    conn.execute(text("""UPDATE verification.decisions SET tg_message_id = :m, sent_at = now()
                         WHERE decision_id = :i"""),
                 {"m": res["message_id"], "i": d["decision_id"]})


# ─────────────────────────────── ask ───────────────────────────────
def validate(category: str, question: str, options: list[dict], recommended: str) -> None:
    if category not in CATEGORIES:
        raise VqError(
            f"카테고리 {category!r} 는 사용자에게 묻지 않는다 — 스스로 결정할 것. "
            f"물을 수 있는 것: {', '.join(CATEGORIES)}")
    if not question or len(question) > 200:
        raise VqError("질문은 1~200자")
    if not 2 <= len(options) <= 4:
        raise VqError("선택지는 2~4개 — 열린 질문('뭘 할까요?')은 보낼 수 없다")
    keys = [o.get("key") for o in options]
    if len(set(keys)) != len(keys) or not all(keys):
        raise VqError("선택지 key 는 비어 있지 않고 서로 달라야 한다")
    for o in options:
        if not o.get("label") or not o.get("consequence"):
            raise VqError(f"선택지 {o.get('key')} 에 label 과 consequence(결과 한 줄)가 필수")
    if recommended not in keys:
        raise VqError("권장안(--recommend)은 선택지 key 중 하나여야 한다")


def parse_option(spec: str) -> dict:
    """'A:지금 실행:러너 lease 대상은 자동 보류' -> {key, label, consequence}."""
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise VqError(f"--option 형식은 KEY:라벨:결과 — 받은 값 {spec!r}")
    return {"key": parts[0].strip(), "label": parts[1].strip(), "consequence": parts[2].strip()}


def ask(*, category: str, question: str, options: list[dict], recommended: str,
        dedupe_key: str, batch_id: int | None = None, issue_id: int | None = None,
        expires_hours: int = 24, apply_default: bool = True,
        now: datetime | None = None, send: bool = True) -> dict:
    _require("fix")
    validate(category, question, options, recommended)
    now = now or datetime.now()
    with _Tx() as conn:
        dup = conn.execute(text("""SELECT decision_id FROM verification.decisions
                                   WHERE dedupe_key = :k AND status = 'pending'"""),
                           {"k": dedupe_key}).scalar()
        if dup:
            return {"decision_id": dup, "sent": False, "reason": "같은 판단이 이미 대기 중"}
        n_pending = conn.execute(text(
            "SELECT count(*) FROM verification.decisions WHERE status = 'pending'")).scalar_one()
        if n_pending >= MAX_PENDING:
            raise VqError(f"대기 중 판단이 이미 {n_pending}건 — 새로 묻지 말고 기존 답을 기다리거나 "
                          f"`vq.py decision cancel` 로 정리할 것")
        quiet = _is_quiet(now)
        if quiet and category != "irreversible":
            raise VqError("야간(22–08시)에는 irreversible 외의 판단은 스스로 내린다(CLAUDE.md 규약)")
        d = dict(conn.execute(text("""
            INSERT INTO verification.decisions
                (category, batch_id, issue_id, question, options, recommended, dedupe_key,
                 nonce, expires_at, apply_default_on_expiry)
            VALUES (:c, :b, :i, :q, CAST(:o AS jsonb), :r, :k, :n, :e, :ad)
            RETURNING *"""),
            {"c": category, "b": batch_id, "i": issue_id, "q": question,
             "o": json.dumps(options, ensure_ascii=False), "r": recommended, "k": dedupe_key,
             "n": secrets.token_hex(4),
             "e": now + timedelta(hours=expires_hours),
             "ad": apply_default and category != "irreversible"}).mappings().one())
        if batch_id:
            conn.execute(text("""UPDATE verification.fix_batches SET status = 'waiting_decision',
                                 updated_at = now() WHERE batch_id = :b"""), {"b": batch_id})
        sent_today = conn.execute(text("""
            SELECT count(*) FROM verification.decisions
            WHERE sent_at >= date_trunc('day', now())""")).scalar_one()
        reason = None
        if quiet:
            reason = "야간 — 08:00 다이제스트가 버튼과 함께 발송"
        elif sent_today >= DAILY_SEND_CAP:
            reason = f"오늘 즉시 발송 {DAILY_SEND_CAP}건 한도 — 다음 다이제스트로"
        elif send:
            try:
                _send(conn, d)
            except TelegramError as exc:
                reason = f"발송 실패({exc}) — 다음 다이제스트가 재시도"
    return {"decision_id": d["decision_id"], "sent": reason is None and send,
            "reason": reason}


# ─────────────────────────────── answer / wait ───────────────────────────────
def record_answer(decision_id: int, *, key: str | None = None, answer_text: str | None = None,
                  via: str, nonce: str | None = None) -> tuple[bool, str]:
    """Returns (recorded, message). Idempotent: a second tap on an answered decision is a no-op."""
    with _Tx(evidence=f"decision #{decision_id} via {via}") as conn:
        d = conn.execute(text("""SELECT * FROM verification.decisions WHERE decision_id = :i
                                 FOR UPDATE"""), {"i": decision_id}).mappings().fetchone()
        if d is None:
            return False, "없는 판단"
        if d["status"] != "pending":
            return False, f"이미 처리됨({d['status']})"
        if nonce is not None and nonce != d["nonce"]:
            return False, "버튼이 오래됐다(nonce 불일치)"
        if key is not None and key not in [o["key"] for o in d["options"]]:
            return False, f"없는 선택지 {key}"
        conn.execute(text("""
            UPDATE verification.decisions
               SET status = 'answered', answer_key = :k, answer_text = :t,
                   answered_via = :v, answered_at = now()
             WHERE decision_id = :i"""),
            {"i": decision_id, "k": key, "t": (answer_text or None) and answer_text[:2000],
             "v": via})
        if d["batch_id"]:
            conn.execute(text("""UPDATE verification.fix_batches SET status = 'open',
                                 updated_at = now()
                                 WHERE batch_id = :b AND status = 'waiting_decision'"""),
                         {"b": d["batch_id"]})
        label = next((o["label"] for o in d["options"] if o["key"] == key), None)
    return True, (f"{key} {label}" if key else "자유 입력 답")


def answer_terminal(decision_id: int, key: str | None, answer_text: str | None) -> str:
    ok, msg = record_answer(decision_id, key=key, answer_text=answer_text, via="terminal")
    if not ok:
        raise VqError(msg)
    _mark_message_answered(decision_id, msg)
    return msg


def _mark_message_answered(decision_id: int, choice: str) -> None:
    with engine.connect() as conn:
        d = _load(conn, decision_id)
    if not d["tg_message_id"]:
        return
    try:
        tg("editMessageText", {
            "chat_id": chat_id(), "message_id": d["tg_message_id"],
            "text": render(d) + f"\n✅ {choice} 선택됨 ({datetime.now():%H:%M})"})
    except TelegramError:
        pass    # cosmetic only; the DB already holds the answer


def wait(decision_id: int, timeout: int = 540, poll: int = 10) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        with engine.connect() as conn:
            d = _load(conn, decision_id)
        if d["status"] != "pending" or time.monotonic() >= deadline:
            return {k: d[k] for k in ("decision_id", "status", "answer_key", "answer_text",
                                      "answered_via", "answered_at")}
        time.sleep(poll)


def cancel(decision_id: int, reason: str) -> None:
    with _Tx(evidence=reason) as conn:
        conn.execute(text("""UPDATE verification.decisions SET status = 'cancelled',
                             answered_at = now(), answer_text = :r
                             WHERE decision_id = :i AND status = 'pending'"""),
                     {"i": decision_id, "r": reason[:2000]})


# ─────────────────────────────── expiry / digest ───────────────────────────────
def expire_due() -> list[int]:
    """Past-due decisions: irreversible stay pending (re-surfaced in the digest, expiry pushed
    by a day); others take the recommended option and say so."""
    done: list[int] = []
    with _Tx(evidence="decision expiry") as conn:
        rows = conn.execute(text("""
            SELECT * FROM verification.decisions
            WHERE status = 'pending' AND expires_at < now() FOR UPDATE""")).mappings().all()
        for d in rows:
            if d["category"] == "irreversible" or not d["apply_default_on_expiry"]:
                conn.execute(text("""UPDATE verification.decisions
                                     SET expires_at = now() + interval '24 hours', sent_at = NULL
                                     WHERE decision_id = :i"""), {"i": d["decision_id"]})
                continue
            conn.execute(text("""
                UPDATE verification.decisions
                   SET status = 'expired', answer_key = recommended, answered_via = 'expiry',
                       answered_at = now()
                 WHERE decision_id = :i"""), {"i": d["decision_id"]})
            if d["batch_id"]:
                conn.execute(text("""UPDATE verification.fix_batches SET status = 'open',
                                     updated_at = now() WHERE batch_id = :b
                                     AND status = 'waiting_decision'"""), {"b": d["batch_id"]})
            done.append(d["decision_id"])
    return done


def send_unsent() -> int:
    """Send pending decisions that were held back (night, cap, failed send). Digest only."""
    n = 0
    with _Tx() as conn:
        rows = conn.execute(text("""
            SELECT * FROM verification.decisions WHERE status = 'pending' AND sent_at IS NULL
            ORDER BY decision_id""")).mappings().all()
        for d in rows:
            try:
                _send(conn, dict(d))
                n += 1
            except TelegramError:
                break
    return n


def pending() -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT decision_id, category, question, recommended, created_at, sent_at, expires_at,
                   batch_id FROM verification.decisions WHERE status = 'pending'
            ORDER BY decision_id""")).mappings()]


# ─────────────────────────────── bot (long polling) ───────────────────────────────
def handle_update(upd: dict, allowed_chat: str) -> str | None:
    """Process one Telegram update. Returns a short log line (never the token)."""
    cq = upd.get("callback_query")
    if cq:
        frm = str((cq.get("from") or {}).get("id"))
        chat = str(((cq.get("message") or {}).get("chat") or {}).get("id"))
        if frm != allowed_chat or chat != allowed_chat:
            return f"ignored callback from {frm}"
        parts = (cq.get("data") or "").split(":")
        if len(parts) != 4 or parts[0] != "d" or not parts[1].isdigit():
            tg("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "알 수 없는 버튼"})
            return "bad callback data"
        did, key, nonce = int(parts[1]), parts[2], parts[3]
        ok, msg = record_answer(did, key=key, via="telegram", nonce=nonce)
        tg("answerCallbackQuery", {"callback_query_id": cq["id"],
                                   "text": ("기록됨: " if ok else "") + msg})
        if ok:
            _mark_message_answered(did, msg)
        return f"decision #{did} callback {key}: {msg}"

    msg = upd.get("message")
    if msg:
        frm = str((msg.get("from") or {}).get("id"))
        chat = str((msg.get("chat") or {}).get("id"))
        if frm != allowed_chat or chat != allowed_chat:
            return f"ignored message from {frm}"
        body = (msg.get("text") or "").strip()
        if body in ("/pending", "/대기"):
            items = pending()
            text_ = ("대기 중 판단 없음" if not items else "\n".join(
                f"#{d['decision_id']} [{d['category']}] {d['question']}" for d in items))
            tg("sendMessage", {"chat_id": allowed_chat, "text": text_})
            return "listed pending"
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        if reply_to:
            with engine.connect() as conn:
                did = conn.execute(text("""SELECT decision_id FROM verification.decisions
                                           WHERE tg_message_id = :m"""), {"m": reply_to}).scalar()
            if did:
                ok, res = record_answer(did, answer_text=body, via="telegram")
                tg("sendMessage", {"chat_id": allowed_chat,
                                   "reply_to_message_id": msg["message_id"],
                                   "text": f"판단 #{did}: " + ("자유 입력 답 기록됨" if ok else res)})
                if ok:
                    _mark_message_answered(did, f"답장: {body[:60]}")
                return f"decision #{did} reply: {res}"
        return None
    return None


def run_bot(poll_timeout: int = 50) -> None:
    """Long-poll loop. Offset persists in verification.kv so a restart never replays taps."""
    from loguru import logger

    allowed = chat_id()
    while True:
        try:
            expire_due()
            with engine.connect() as conn:
                off = conn.execute(text(
                    "SELECT value FROM verification.kv WHERE key = 'tg_offset'")).scalar()
            payload = {"timeout": poll_timeout,
                       "allowed_updates": ["callback_query", "message"]}
            if off:
                payload["offset"] = int(off)
            updates = tg("getUpdates", payload, timeout=poll_timeout + 15)
            for upd in updates:
                try:
                    line = handle_update(upd, allowed)
                    if line:
                        logger.info(f"[decision_bot] {line}")
                except Exception as exc:  # noqa: BLE001 — one bad update must not stop the bot
                    logger.warning(f"[decision_bot] update failed: {type(exc).__name__}: {exc}")
                with _Tx() as conn:
                    conn.execute(text("""
                        INSERT INTO verification.kv (key, value, updated_at)
                        VALUES ('tg_offset', :v, now())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""),
                        {"v": str(upd["update_id"] + 1)})
        except TelegramError as exc:
            logger.warning(f"[decision_bot] {exc}")
            time.sleep(30)
        except Exception as exc:  # noqa: BLE001 — DB restart etc.; keep the daemon alive
            logger.warning(f"[decision_bot] loop error: {type(exc).__name__}: {exc}")
            time.sleep(30)
