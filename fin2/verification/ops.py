"""Verification campaign operations — everything `scripts/vq.py` does, as plain functions.

State lives only in the `verification` schema (fin2/verification/schema.sql). Nothing here
keeps state in memory between commands, so any session in either worktree can resume.

Roles (decided by the DB login, see schema.sql::actor_role):
  verify (camp_run)        claim/show/pass/skip/issue add/done, recheck/close/reopen
  fix    (camp_err_review) fix-queue, batch new/reload/mark-fixed, ask
  admin  (main checkout)   init/import/sync, anything
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from collector.db import engine
from fin2.verification.session_info import REPO_ROOT, parser_commit, worktree_name

DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}"
LEASE_MINUTES = 120
MAX_RETRIES = 3
ALL_SCOPES = tuple(f"{p}-{s}" for p in ("sep", "con") for s in ("bs", "is", "cf", "sce"))
_PERIOD_ORDER = "CASE p.fiscal_period WHEN 'FY' THEN 4 WHEN 'Q3' THEN 3 WHEN 'H1' THEN 2 ELSE 1 END"

# Eras in global priority order: every company's 2015+ comes before any 2011-14 slot
# (same rule as scripts/layer2_review.py _ERA_RANK_SQL).
ERAS = {"2015+": (1, 2015, 9999), "2011-14": (2, 2011, 2014),
        "2007-10": (3, 2007, 2010), "pre-2007": (4, 1999, 2006)}


class VqError(RuntimeError):
    """A refused operation. The message is meant for the operator (Korean)."""


@dataclass(frozen=True)
class Slot:
    corp_code: str
    fiscal_year: int
    fiscal_period: str

    @classmethod
    def parse(cls, s: str) -> "Slot":
        try:
            corp, fy, fp = s.split(":")
            return cls(corp, int(fy), fp.upper())
        except ValueError as exc:
            raise VqError(f"슬롯 형식은 CORP:YEAR:PERIOD (예 00126380:2024:FY) — 받은 값 {s!r}") from exc

    def __str__(self) -> str:
        return f"{self.corp_code}:{self.fiscal_year}:{self.fiscal_period}"

    def params(self) -> dict:
        return {"c": self.corp_code, "y": self.fiscal_year, "p": self.fiscal_period}


def _begin(evidence: str | None = None, reason: str | None = None):
    """Transaction with optional per-transaction GUCs read by the triggers."""
    conn = engine.connect()
    trans = conn.begin()
    if evidence:
        conn.execute(text("SELECT set_config('verification.evidence', :e, true)"),
                     {"e": evidence[:2000]})
    if reason:
        conn.execute(text("SELECT set_config('verification.load_reason', :r, true)"),
                     {"r": reason[:120]})
    return conn, trans


class _Tx:
    def __init__(self, evidence: str | None = None, reason: str | None = None):
        self.evidence, self.reason = evidence, reason

    def __enter__(self):
        self.conn, self.trans = _begin(self.evidence, self.reason)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.trans.commit()
            else:
                self.trans.rollback()
        finally:
            self.conn.close()
        return False


def role() -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT verification.actor_role()")).scalar_one()


def whoami() -> dict:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT session_user::text AS db_user, verification.actor_role() AS role, "
            "verification.actor() AS actor, current_setting('verification.parser_commit', true) "
            "AS parser_commit")).mappings().one()
    return {**row, "worktree": worktree_name(), "repo": str(REPO_ROOT)}


def _require(*allowed: str) -> str:
    r = role()
    if r not in allowed and r != "admin":
        raise VqError(f"이 명령은 {'/'.join(allowed)} 역할 전용이다(현재 {r}). "
                      f"워크트리 .env 의 DATABASE_URL 을 확인할 것.")
    return r


# ═══════════════════════════════ init / sync ═══════════════════════════════
# Same universe as scripts/layer2_review.py (_UNIVERSE_SQL): active listed common stock,
# foreign issuers (stock_code 9xxxxx, R7) excluded, ranked by latest market cap.
_UNIVERSE_SQL = """
    WITH last_close AS (
        SELECT DISTINCT ON (stock_code) stock_code, close_price
        FROM stock_prices WHERE close_price IS NOT NULL
        ORDER BY stock_code, trade_date DESC
    ), last_shares AS (
        SELECT DISTINCT ON (corp_code) corp_code, shares_out
        FROM report_shares_outstanding
        ORDER BY corp_code, as_of_date DESC NULLS LAST, rcept_no DESC
    )
    SELECT c.corp_code,
           row_number() OVER (ORDER BY lc.close_price::bigint * ls.shares_out DESC NULLS LAST,
                              c.corp_code) AS corp_rank
    FROM corporations c
    LEFT JOIN last_close lc ON lc.stock_code = c.stock_code
    LEFT JOIN last_shares ls ON ls.corp_code = c.corp_code
    WHERE c.is_active AND c.stock_code IS NOT NULL AND c.stock_code NOT LIKE '9' || '%'
      AND c.coverage_class = 'periodic'
"""


def init_era(era: str = "2015+") -> dict:
    """Create/refresh slots and their filings for one era. Idempotent: verdicts are kept,
    only corp_rank is refreshed; new filings join as pending (and demote a passed slot)."""
    _require("admin")
    if era not in ERAS:
        raise VqError(f"알 수 없는 era {era!r} — {', '.join(ERAS)}")
    era_rank, fy_min, fy_max = ERAS[era]
    with _Tx(evidence=f"init {era}") as conn:
        conn.execute(text(f"CREATE TEMP TABLE _u ON COMMIT DROP AS {_UNIVERSE_SQL}"))
        conn.execute(text("""
            CREATE TEMP TABLE _f ON COMMIT DROP AS
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
                   coalesce(f.is_amendment, false) AS is_amendment,
                   row_number() OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period
                                      ORDER BY f.filed_at NULLS LAST, f.rcept_no) AS seq
            FROM filings f JOIN _u USING (corp_code)
            WHERE f.report_type IN ('annual', 'half', 'quarter')
              AND f.fiscal_period IN ('Q1', 'H1', 'Q3', 'FY')
              AND f.fiscal_year BETWEEN :lo AND :hi
              AND f.fiscal_year <= extract(year FROM now())::int
              AND (f.report_nm IS NULL OR position('제출기한연장신고서' IN f.report_nm) = 0)
        """), {"lo": fy_min, "hi": fy_max})
        n_slots = conn.execute(text("""
            INSERT INTO verification.progress
                (corp_code, fiscal_year, fiscal_period, era, era_rank, corp_rank)
            SELECT DISTINCT f.corp_code, f.fiscal_year, f.fiscal_period, :era, :er, u.corp_rank
            FROM _f f JOIN _u u USING (corp_code)
            ON CONFLICT (corp_code, fiscal_year, fiscal_period)
            DO UPDATE SET corp_rank = EXCLUDED.corp_rank
        """), {"era": era, "er": era_rank}).rowcount
        conn.execute(text("""
            CREATE TEMP TABLE _new ON COMMIT DROP AS
            SELECT rcept_no, corp_code, fiscal_year, fiscal_period, seq, is_amendment FROM _f
            WHERE NOT EXISTS (SELECT 1 FROM verification.progress_filings pf
                               WHERE pf.rcept_no = _f.rcept_no)"""))
        n_new = conn.execute(text("""
            INSERT INTO verification.progress_filings
                (rcept_no, corp_code, fiscal_year, fiscal_period, seq_in_slot, is_amendment)
            SELECT rcept_no, corp_code, fiscal_year, fiscal_period, seq, is_amendment FROM _new
            ON CONFLICT (rcept_no) DO NOTHING""")).rowcount
        # Only a passed slot changes state when a filing joins it (it must be re-verified);
        # refreshing every fresh slot on the first init would be pure cost.
        conn.execute(text("""
            SELECT verification.refresh_slot(p.corp_code, p.fiscal_year, p.fiscal_period)
            FROM verification.progress p
            WHERE p.status = 'passed' AND EXISTS (
                SELECT 1 FROM _new n WHERE n.corp_code = p.corp_code
                   AND n.fiscal_year = p.fiscal_year AND n.fiscal_period = p.fiscal_period)"""))
        conn.execute(text("""
            INSERT INTO verification.kv (key, value, updated_at)
            VALUES ('last_sync', now()::text, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""))
    return {"era": era, "slots_upserted": n_slots, "new_filings": n_new}


def sync_if_stale(hours: int = 6) -> dict | None:
    """Pick up new filings/slots at most every few hours (called by the runner's claim)."""
    with engine.connect() as conn:
        last = conn.execute(text(
            "SELECT updated_at FROM verification.kv WHERE key = 'last_sync'")).scalar()
        stale = last is None or conn.execute(text(
            "SELECT :t < now() - make_interval(hours => :h)"),
            {"t": last, "h": hours}).scalar()
    if not stale or role() != "admin":
        return None
    return init_era("2015+")


# ═══════════════════════════════ import legacy queue ═══════════════════════════════
def import_legacy_queue(dry_run: bool = True) -> dict:
    """layer2_review_queue verdicts → progress_filings (2015+ only).

    pass → passed (scopes/note/time kept; baseline = current content, see design §6),
    skipped → skipped. fail/blocked/reloaded stay pending: they get re-verified, and the
    camp_run markdown issues are imported separately.
    """
    _require("admin")
    with _Tx(evidence="import layer2_review_queue") as conn:
        counts = dict(conn.execute(text("""
            SELECT q.status, count(*) FROM layer2_review_queue q
            JOIN verification.progress_filings pf USING (rcept_no)
            GROUP BY q.status""")).fetchall())
        missing = conn.execute(text("""
            SELECT q.status, count(*) FROM layer2_review_queue q
            WHERE q.fiscal_year >= 2015 AND q.status IN ('pass', 'skipped')
              AND NOT EXISTS (SELECT 1 FROM verification.progress_filings pf
                               WHERE pf.rcept_no = q.rcept_no)
            GROUP BY q.status""")).fetchall()
        out = {"queue_status_in_scope": counts, "not_in_universe": dict(missing)}
        if dry_run:
            return out
        passed = conn.execute(text("""
            SELECT q.rcept_no, q.verified_scopes, q.note, q.reviewed_at, q.owner
            FROM layer2_review_queue q JOIN verification.progress_filings pf USING (rcept_no)
            WHERE q.status = 'pass' AND pf.status = 'pending'""")).mappings().all()
        for r in passed:
            conn.execute(text("SELECT verification.ensure_baseline(:r)"), {"r": r["rcept_no"]})
            scopes = [s.strip() for s in (r["verified_scopes"] or "").split(",") if s.strip()]
            conn.execute(text("""
                UPDATE verification.progress_filings pf
                   SET status = 'passed', verified_load_seq = fl.load_seq,
                       verified_scopes = CAST(:sc AS text[]),
                       verified_scope_hashes = fl.scope_hashes,
                       verified_at = coalesce(:at, now()), verified_by = :by,
                       note = left('[legacy layer2_review pass] ' || coalesce(:note, ''), 2000),
                       updated_at = now()
                  FROM verification.filing_loads fl
                 WHERE pf.rcept_no = :r AND fl.rcept_no = pf.rcept_no"""),
                {"r": r["rcept_no"], "sc": scopes or None, "at": r["reviewed_at"],
                 "by": r["owner"] or "legacy", "note": r["note"]})
        skipped = conn.execute(text("""
            UPDATE verification.progress_filings pf
               SET status = 'skipped', verified_at = coalesce(q.reviewed_at, now()),
                   verified_by = coalesce(q.owner, 'legacy'),
                   note = left('[legacy layer2_review skip] ' || coalesce(q.note, ''), 2000),
                   updated_at = now()
              FROM layer2_review_queue q
             WHERE q.rcept_no = pf.rcept_no AND q.status = 'skipped'
               AND pf.status = 'pending'""")).rowcount
        slots = conn.execute(text("""
            SELECT DISTINCT pf.corp_code, pf.fiscal_year, pf.fiscal_period
            FROM verification.progress_filings pf JOIN layer2_review_queue q USING (rcept_no)
            WHERE q.status IN ('pass', 'skipped')""")).fetchall()
        for c, y, p in slots:
            conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"),
                         {"c": c, "y": y, "p": p})
        out.update({"imported_pass": len(passed), "imported_skipped": skipped,
                    "slots_refreshed": len(slots)})
    return out


# ═══════════════════════════════ claim / show ═══════════════════════════════
def _reap_expired(conn) -> int:
    """Expired leases (crashed session) go back to the queue with retry_count + 1."""
    rows = conn.execute(text("""
        UPDATE verification.progress
           SET status = CASE WHEN retry_count + 1 >= :mx THEN 'blocked' ELSE 'pending' END,
               retry_count = retry_count + 1, claimed_by = NULL, lease_until = NULL,
               note = CASE WHEN retry_count + 1 >= :mx
                           THEN left(coalesce(note || ' / ', '') || 'lease expired ' ||
                                     (retry_count + 1) || 'x -> blocked', 2000) ELSE note END,
               updated_at = now()
         WHERE status = 'in_progress' AND lease_until < now()
        RETURNING corp_code, fiscal_year, fiscal_period, status"""),
        {"mx": MAX_RETRIES}).fetchall()
    for c, y, p, st in rows:
        if st != "blocked":
            conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"),
                         {"c": c, "y": y, "p": p})
    return len(rows)


def own_slot() -> Slot | None:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period FROM verification.progress
            WHERE status = 'in_progress' AND claimed_by = verification.actor()
            ORDER BY claimed_at LIMIT 1""")).fetchone()
    return Slot(*row) if row else None


# Model-review gate (kv machine.gate = on): a pending slot goes to the model reviewer only once
# the machine pass has looked at every pending filing at its current load and left something
# for a human eye - a finding, no usable source, or the 1% audit draw. Slots with fixed issues
# (re-check) are always eligible. Design: docs/plans/verification_machine_compare_design_2026-09-24.md
MODEL_READY_SQL = """
    ((p.status = 'has_issues' AND EXISTS (
        -- re-checks of machine-registered issues belong to `vq.py machine recheck`
        SELECT 1 FROM verification.issues i
        WHERE i.corp_code = p.corp_code AND i.fiscal_year = p.fiscal_year
          AND i.fiscal_period = p.fiscal_period AND i.status = 'fixed'
          AND i.created_by NOT LIKE '%machine'))
     OR (p.status = 'pending' AND NOT EXISTS (
        SELECT 1 FROM verification.progress_filings pf
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        LEFT JOIN verification.machine_checks mc USING (rcept_no)
        WHERE pf.corp_code = p.corp_code AND pf.fiscal_year = p.fiscal_year
          AND pf.fiscal_period = p.fiscal_period AND pf.status = 'pending'
          AND (mc.rcept_no IS NULL OR mc.load_seq IS DISTINCT FROM fl.load_seq
               OR (mc.tool_version <> '{tool}' AND mc.verdict IN ('mismatch', 'error'))))))"""


def _model_ready_sql() -> str:
    # an older machine tool's mismatch is re-done by the machine before the model sees it
    from fin2.verification.machine_compare import TOOL_VERSION
    return MODEL_READY_SQL.format(tool=TOOL_VERSION)


def machine_gate_on(conn) -> bool:
    v = conn.execute(text("SELECT value FROM verification.kv WHERE key = 'machine.gate'")).scalar()
    return (v or "off").strip().lower() == "on"


def claim(slot: Slot | None = None, lease_minutes: int = LEASE_MINUTES,
          where: str | None = None) -> Slot | None:
    """Claim the next slot (or a named one). Priority:
    1. slots with fixed issues waiting for a re-check,
    2. pending slots that were verified before (reload / closed issue → re-compare),
    3. everything else by era → market-cap rank → latest year → latest period.
    `where` narrows the pick (the machine pass passes its own filter); without it the model
    gate applies when kv machine.gate = on.
    """
    _require("verify")
    sync_if_stale()
    with _Tx(evidence="claim") as conn:
        _reap_expired(conn)
        if slot is None:
            extra = where or (_model_ready_sql() if machine_gate_on(conn) else "TRUE")
            row = conn.execute(text(f"""
                SELECT p.corp_code, p.fiscal_year, p.fiscal_period
                FROM verification.progress p
                WHERE p.status IN ('pending', 'has_issues')
                  AND (p.status = 'pending' OR EXISTS (
                        SELECT 1 FROM verification.issues i
                         WHERE i.corp_code = p.corp_code AND i.fiscal_year = p.fiscal_year
                           AND i.fiscal_period = p.fiscal_period AND i.status = 'fixed'))
                  AND {extra}
                ORDER BY
                  (p.status = 'has_issues') DESC,
                  EXISTS (SELECT 1 FROM verification.progress_filings pf
                           WHERE pf.corp_code = p.corp_code AND pf.fiscal_year = p.fiscal_year
                             AND pf.fiscal_period = p.fiscal_period
                             AND pf.verified_at IS NOT NULL) DESC,
                  p.era_rank, p.corp_rank NULLS LAST, p.fiscal_year DESC, {_PERIOD_ORDER} DESC
                LIMIT 1
                FOR UPDATE SKIP LOCKED""")).fetchone()
            if row is None:
                return None
            slot = Slot(*row)
        got = conn.execute(text("""
            UPDATE verification.progress
               SET status = 'in_progress', claimed_by = verification.actor(),
                   claimed_at = now(), lease_until = now() + make_interval(mins => :m),
                   updated_at = now()
             WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p
               AND (status IN ('pending', 'has_issues')
                    OR (status = 'in_progress' AND claimed_by = verification.actor()))
            RETURNING 1"""), {**slot.params(), "m": lease_minutes}).fetchone()
        if got is None:
            raise VqError(f"{slot} 는 지금 점유할 수 없다(다른 세션 점유 중이거나 passed/blocked).")
        for (rcept,) in conn.execute(text("""
                SELECT rcept_no FROM verification.progress_filings
                WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p"""),
                slot.params()).fetchall():
            seq = conn.execute(text("SELECT verification.ensure_baseline(:r)"),
                               {"r": rcept}).scalar_one()
            conn.execute(text("UPDATE verification.progress_filings SET claim_load_seq = :s "
                              "WHERE rcept_no = :r"), {"s": seq, "r": rcept})
    return slot


def _slot_row(conn, slot: Slot) -> dict:
    row = conn.execute(text("""
        SELECT p.*, c.corp_name, c.market FROM verification.progress p
        JOIN corporations c USING (corp_code)
        WHERE p.corp_code = :c AND p.fiscal_year = :y AND p.fiscal_period = :p"""),
        slot.params()).mappings().fetchone()
    if row is None:
        raise VqError(f"슬롯 {slot} 없음")
    return dict(row)


def slot_detail(slot: Slot) -> dict:
    """Everything a reviewer needs for one slot, read-only."""
    with engine.connect() as conn:
        info = _slot_row(conn, slot)
        filings = [dict(r) for r in conn.execute(text("""
            SELECT pf.*, f.report_nm, f.filed_at, f.report_type,
                   fl.load_seq, fl.parser_commit, fl.scope_hashes, fl.n_lines, fl.baseline,
                   fl.loaded_at,
                   mc.verdict AS machine_verdict, mc.audit AS machine_audit,
                   mc.counts AS machine_counts, mc.findings AS machine_findings,
                   mc.tool_version AS machine_tool,
                   (mc.load_seq IS NOT DISTINCT FROM fl.load_seq) AS machine_current
            FROM verification.progress_filings pf
            JOIN filings f USING (rcept_no)
            LEFT JOIN verification.filing_loads fl USING (rcept_no)
            LEFT JOIN verification.machine_checks mc USING (rcept_no)
            WHERE pf.corp_code = :c AND pf.fiscal_year = :y AND pf.fiscal_period = :p
            ORDER BY pf.seq_in_slot, pf.rcept_no"""), slot.params()).mappings()]
        counts = conn.execute(text("""
            SELECT rcept_no, basis, statement, count(*) AS n FROM report_lines
            WHERE rcept_no = ANY(:rs) AND statement IN ('BS', 'IS', 'CF', 'SCE')
            GROUP BY 1, 2, 3"""), {"rs": [f["rcept_no"] for f in filings]}).fetchall()
        issues = [dict(r) for r in conn.execute(text("""
            SELECT issue_id, rcept_no, basis, statement, account_label, column_label,
                   db_value, source_value, source_value_raw, source_unit, error_type, status,
                   rule_id, fix_batch_id
            FROM verification.issues
            WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p
              AND status <> 'closed'
            ORDER BY issue_id"""), slot.params()).mappings()]
    by_rcept: dict[str, dict[str, int]] = {}
    for r, basis, stmt, n in counts:
        code = ("sep" if basis == "separate" else "con") + "-" + stmt.lower()
        by_rcept.setdefault(r, {})[code] = n
    for f in filings:
        f["dart_url"] = DART_URL.format(rcept=f["rcept_no"])
        f["scope_rows"] = {s: by_rcept.get(f["rcept_no"], {}).get(s)
                           for s in ALL_SCOPES if by_rcept.get(f["rcept_no"], {}).get(s)}
        now_h = f.get("scope_hashes") or {}
        old_h = f.get("verified_scope_hashes") or {}
        f["changed_since_verified"] = (
            sorted(s for s in set(now_h) | set(old_h) if now_h.get(s) != old_h.get(s))
            if old_h else None)
    # Byte-identical scopes between filings of the same slot (amendment shortcut).
    for f in filings:
        same = {}
        for g in filings:
            if g is f or g["seq_in_slot"] >= f["seq_in_slot"]:
                continue
            ident = sorted(s for s, h in (f.get("scope_hashes") or {}).items()
                           if (g.get("scope_hashes") or {}).get(s) == h)
            if ident:
                same[g["rcept_no"]] = ident
        f["identical_to_earlier"] = same
    return {"slot": info, "filings": filings, "open_issues": issues}


def write_review_csvs(slot: Slot, detail: dict) -> dict[str, str]:
    """Regenerate the existing review CSV (fin2/extract/review_csv.py) per filing. Read-only
    on the DB: the self-checks parse the source file in memory and store nothing."""
    from collector.db import get_session
    from fin2.audit import layer2_selfcheck as sc
    from fin2.audit import orphan_tables, row_coverage
    from fin2.extract import review_csv
    from fin2.extract.report_lines import extract_report_lines

    info = detail["slot"]
    out: dict[str, str] = {}
    with get_session() as session:
        for f in detail["filings"]:
            src = session.execute(text("""
                SELECT file_type, file_path FROM download_tasks
                WHERE rcept_no = :r AND status = 'completed' AND file_path IS NOT NULL
                ORDER BY CASE file_type WHEN 'xml' THEN 0 WHEN 'pdf' THEN 1 ELSE 2 END"""),
                {"r": f["rcept_no"]}).fetchall()
            kind, path = "none", None
            for ft, fp in src:
                if Path(fp).exists():
                    kind, path = ft or "unknown", fp
                    break
            rows = sc.load_rows(session, f["rcept_no"])
            checks = sc.run_checks(session, f["rcept_no"], corp_code=info["corp_code"],
                                   fiscal_period=info["fiscal_period"], rows=rows)
            missing = None
            if kind == "xml":
                lines = extract_report_lines(
                    path, rcept_no=f["rcept_no"], corp_code=info["corp_code"],
                    report_fiscal_year=info["fiscal_year"],
                    report_fiscal_period=info["fiscal_period"], include_notes=False)
                checks.append(orphan_tables.check(path))
                missing, row_check = row_coverage.scan(path, lines)
                checks.append(row_check)
            csv, _ = review_csv.generate(
                session, rcept_no=f["rcept_no"], corp_code=info["corp_code"],
                corp_name=info["corp_name"], market=info["market"],
                corp_rank=info["corp_rank"], report_type=f["report_type"],
                report_nm=f["report_nm"], fiscal_year=info["fiscal_year"],
                fiscal_period=info["fiscal_period"], filed_at=f["filed_at"],
                source_kind=kind, checks=checks, reloaded_at=f.get("loaded_at"),
                root=REPO_ROOT / "layer2_review", db_rows=rows, source_only_rows=missing)
            out[f["rcept_no"]] = str(csv)
            session.rollback()
    return out


# ═══════════════════════════════ verdicts ═══════════════════════════════
def _own_claim(conn, slot: Slot) -> None:
    ok = conn.execute(text("""
        SELECT verification.actor_role() = 'admin' OR (status = 'in_progress'
               AND claimed_by = verification.actor())
        FROM verification.progress
        WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p"""),
        slot.params()).scalar()
    if not ok:
        raise VqError(f"{slot} 는 이 세션이 점유한 슬롯이 아니다 — `vq.py next` 로 점유 후 진행.")


def _filing(conn, rcept: str) -> dict:
    row = conn.execute(text("""
        SELECT pf.*, fl.load_seq, fl.scope_hashes FROM verification.progress_filings pf
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        WHERE pf.rcept_no = :r"""), {"r": rcept}).mappings().fetchone()
    if row is None:
        raise VqError(f"{rcept} 는 검증 대상 필링이 아니다")
    return dict(row)


def _check_version(f: dict) -> None:
    if f["claim_load_seq"] is not None and f["load_seq"] != f["claim_load_seq"]:
        raise VqError(
            f"{f['rcept_no']} 는 점유 이후 재적재됐다(load_seq {f['claim_load_seq']} → "
            f"{f['load_seq']}). `vq.py show` 로 바뀐 scope 를 확인하고 다시 대조할 것.")


def pass_filing(rcept: str, scopes: list[str], note: str | None) -> dict:
    _require("verify")
    with _Tx(evidence=note or "pass") as conn:
        f = _filing(conn, rcept)
        slot = Slot(f["corp_code"], f["fiscal_year"], f["fiscal_period"])
        _own_claim(conn, slot)
        _check_version(f)
        loaded = sorted((f["scope_hashes"] or {}).keys())
        given = sorted(set(scopes))
        if not loaded:
            raise VqError(f"{rcept} 는 적재된 scope 가 없다 — 원문에 표가 없으면 "
                          f"`vq.py skip --rcept {rcept} --note ...` 로 처리.")
        unknown = [s for s in given if s not in ALL_SCOPES]
        if unknown:
            raise VqError(f"알 수 없는 scope {unknown} — 사용 가능: {', '.join(ALL_SCOPES)}")
        if given != loaded:
            raise VqError(
                f"--verified-scopes 가 실제 적재 scope 와 다르다.\n"
                f"  적재됨: {','.join(loaded)}\n  입력:   {','.join(given)}\n"
                f"  빠짐: {sorted(set(loaded) - set(given))}  남음: {sorted(set(given) - set(loaded))}\n"
                f"적재된 scope 는 전부 원문과 대조해야 pass 할 수 있다(8scope 전체대조 규약).")
        n_open = conn.execute(text(
            "SELECT count(*) FROM verification.issues WHERE rcept_no = :r AND status <> 'closed'"),
            {"r": rcept}).scalar_one()
        if n_open:
            raise VqError(f"{rcept} 에 미해결 이슈 {n_open}건 — pass 불가(`vq.py done` 으로 슬롯 종료).")
        conn.execute(text("""
            UPDATE verification.progress_filings
               SET status = 'passed', verified_load_seq = :s, verified_scopes = CAST(:sc AS text[]),
                   verified_scope_hashes = CAST(:h AS jsonb), verified_at = now(),
                   verified_by = verification.actor(), note = :n, updated_at = now()
             WHERE rcept_no = :r"""),
            {"r": rcept, "s": f["load_seq"], "sc": given,
             "h": json.dumps(f["scope_hashes"]), "n": (note or "")[:2000] or None})
    return {"rcept_no": rcept, "status": "passed", "scopes": given}


def skip_filing(rcept: str, note: str) -> dict:
    _require("verify")
    if not note:
        raise VqError("skip 에는 --note(사유)가 필수")
    with _Tx(evidence=note) as conn:
        f = _filing(conn, rcept)
        _own_claim(conn, Slot(f["corp_code"], f["fiscal_year"], f["fiscal_period"]))
        conn.execute(text("""
            UPDATE verification.progress_filings SET status = 'skipped', verified_at = now(),
                   verified_by = verification.actor(), note = :n, updated_at = now()
             WHERE rcept_no = :r"""), {"r": rcept, "n": note[:2000]})
    return {"rcept_no": rcept, "status": "skipped"}


_ISSUE_FIELDS = ("basis", "statement", "account_label", "column_label", "db_label",
                 "db_row_order", "db_value", "source_value", "source_value_raw", "source_unit",
                 "error_type", "evidence", "rule_id")


def add_issues(rcept: str, items: list[dict]) -> list[int]:
    """Register one or more cell mismatches for a filing of the claimed slot."""
    _require("verify")
    ids = []
    with _Tx() as conn:
        f = _filing(conn, rcept)
        slot = Slot(f["corp_code"], f["fiscal_year"], f["fiscal_period"])
        _own_claim(conn, slot)
        _check_version(f)
        for it in items:
            bad = set(it) - set(_ISSUE_FIELDS)
            if bad:
                raise VqError(f"알 수 없는 이슈 필드 {sorted(bad)}")
            for req in ("basis", "statement", "account_label", "error_type"):
                if not it.get(req):
                    raise VqError(f"이슈 필드 {req} 필수")
            row = {k: it.get(k) for k in _ISSUE_FIELDS}
            row.update(slot.params(), r=rcept, url=DART_URL.format(rcept=rcept))
            conn.execute(text("SELECT set_config('verification.evidence', :e, true)"),
                         {"e": (it.get("evidence") or "")[:2000]})
            ids.append(conn.execute(text("""
                INSERT INTO verification.issues
                    (corp_code, fiscal_year, fiscal_period, rcept_no, basis, statement,
                     account_label, column_label, db_label, db_row_order, db_value,
                     source_value, source_value_raw, source_unit, error_type, evidence,
                     rule_id, dart_url)
                VALUES (:c, :y, :p, :r, :basis, :statement, :account_label, :column_label,
                        :db_label, :db_row_order, :db_value, :source_value, :source_value_raw,
                        :source_unit, :error_type, :evidence, :rule_id, :url)
                RETURNING issue_id"""), row).scalar_one())
    return ids


def done(slot: Slot | None = None) -> dict:
    """Release the claimed slot; its status is derived from filings + open issues."""
    _require("verify")
    slot = slot or own_slot()
    if slot is None:
        raise VqError("점유 중인 슬롯이 없다")
    with _Tx(evidence="done") as conn:
        _own_claim(conn, slot)
        conn.execute(text("""
            UPDATE verification.progress
               SET status = 'pending', claimed_by = NULL, lease_until = NULL, updated_at = now()
             WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p"""), slot.params())
        conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"), slot.params())
        st = conn.execute(text("""
            SELECT status FROM verification.progress
            WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p"""),
            slot.params()).scalar_one()
        left = conn.execute(text("""
            SELECT array_agg(rcept_no) FROM verification.progress_filings
            WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p
              AND status = 'pending'"""), slot.params()).scalar()
    outcome = {"passed": "passed", "has_issues": "has_issues"}.get(st, "incomplete")
    return {"slot": str(slot), "status": st, "outcome": outcome, "unverified": left or []}


def release(slot: Slot, *, failed: bool, note: str | None = None) -> dict:
    """Runner-side release after a run that did not call `done` (crash/timeout)."""
    with _Tx(evidence=note or "runner release") as conn:
        row = conn.execute(text("""
            UPDATE verification.progress
               SET status = CASE WHEN :f AND retry_count + 1 >= :mx THEN 'blocked'
                                 ELSE 'pending' END,
                   retry_count = retry_count + CASE WHEN :f THEN 1 ELSE 0 END,
                   claimed_by = NULL, lease_until = NULL,
                   note = CASE WHEN :n IS NULL THEN note ELSE left(:n, 2000) END,
                   updated_at = now()
             WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = :p
               AND status = 'in_progress'
            RETURNING status"""), {**slot.params(), "f": failed, "mx": MAX_RETRIES,
                                   "n": note}).fetchone()
        if row and row[0] != "blocked":
            conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"), slot.params())
    return {"slot": str(slot), "status": row[0] if row else None}


def slot_status(slot: Slot) -> str:
    with engine.connect() as conn:
        return _slot_row(conn, slot)["status"]


# ═══════════════════════════════ recheck (verify) ═══════════════════════════════
def _current_db_value(conn, issue: dict):
    label = issue["db_label"] or issue["account_label"]
    return conn.execute(text("""
        SELECT array_agg(value_won ORDER BY row_order) FROM report_lines
        WHERE rcept_no = :r AND basis = :b AND statement = :s AND label_raw = :l
          AND (CAST(:cl AS text) IS NULL OR col_label = :cl)"""),
        {"r": issue["rcept_no"], "b": issue["basis"],
         "s": "IS" if issue["statement"] == "CIS" else issue["statement"],
         "l": label, "cl": issue["column_label"]}).scalar()


def recheck_list(slot: Slot | None = None) -> list[dict]:
    with engine.connect() as conn:
        q = """SELECT * FROM verification.issues WHERE status = 'fixed'"""
        params: dict = {}
        if slot:
            q += " AND corp_code = :c AND fiscal_year = :y AND fiscal_period = :p"
            params = slot.params()
        rows = [dict(r) for r in conn.execute(text(q + " ORDER BY issue_id"), params).mappings()]
        for r in rows:
            r["db_value_now"] = _current_db_value(conn, r)
    return rows


def transition(issue_id: int, to: str, evidence: str | None) -> dict:
    with _Tx(evidence=evidence) as conn:
        row = conn.execute(text("""
            UPDATE verification.issues SET status = :t WHERE issue_id = :i
            RETURNING issue_id, status, corp_code, fiscal_year, fiscal_period"""),
            {"i": issue_id, "t": to}).mappings().fetchone()
        if row is None:
            raise VqError(f"이슈 #{issue_id} 없음")
    return dict(row)


# ═══════════════════════════════ fix side ═══════════════════════════════
def fix_queue() -> dict:
    with engine.connect() as conn:
        groups = [dict(r) for r in conn.execute(text("""
            SELECT i.error_type, et.label_ko, count(*) AS n_issues,
                   count(DISTINCT i.rcept_no) AS n_filings, count(DISTINCT i.corp_code) AS n_corps,
                   count(*) FILTER (WHERE i.status = 'reopened') AS n_reopened,
                   min(i.issue_id) AS first_issue
            FROM verification.issues i JOIN verification.error_types et ON et.code = i.error_type
            WHERE i.status IN ('open', 'reopened') AND i.fix_batch_id IS NULL
            GROUP BY 1, 2 ORDER BY n_issues DESC""")).mappings()]
        batches = [dict(r) for r in conn.execute(text("""
            SELECT b.batch_id, b.error_type, b.rule_id, b.title, b.status, b.created_at,
                   (SELECT count(*) FROM verification.issues i WHERE i.fix_batch_id = b.batch_id
                     AND i.status = 'fixing') AS n_fixing,
                   (SELECT count(*) FROM verification.batch_targets t
                     WHERE t.batch_id = b.batch_id AND t.status IN ('pending', 'deferred'))
                     AS n_to_reload,
                   (SELECT count(*) FROM verification.decisions d WHERE d.batch_id = b.batch_id
                     AND d.status = 'answered'
                     AND d.answered_at > coalesce(b.updated_at, b.created_at)) AS n_answered
            FROM verification.fix_batches b
            WHERE b.status IN ('open', 'waiting_decision', 'reloading')
            ORDER BY n_answered DESC, b.status = 'reloading' DESC, b.batch_id""")).mappings()]
        decisions = [dict(r) for r in conn.execute(text("""
            SELECT decision_id, category, batch_id, question, status, answer_key, answer_text,
                   answered_at FROM verification.decisions
            WHERE status = 'pending' OR (status = 'answered' AND answered_at > now() - interval '3 days')
            ORDER BY decision_id DESC LIMIT 20""")).mappings()]
    return {"groups": groups, "batches": batches, "decisions": decisions}


def issues_of_type(error_type: str, statuses=("open", "reopened")) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT i.*, c.corp_name FROM verification.issues i JOIN corporations c USING (corp_code)
            WHERE i.error_type = :t AND i.status = ANY(:s) AND i.fix_batch_id IS NULL
            ORDER BY i.issue_id"""), {"t": error_type, "s": list(statuses)}).mappings()]


def batch_new(error_type: str, title: str, issue_ids: list[int] | None,
              rule_id: str | None = None) -> dict:
    _require("fix")
    with _Tx(evidence=f"batch new: {title}") as conn:
        bid = conn.execute(text("""
            INSERT INTO verification.fix_batches (error_type, rule_id, title)
            VALUES (:t, :r, :ti) RETURNING batch_id"""),
            {"t": error_type, "r": rule_id, "ti": title[:200]}).scalar_one()
        if issue_ids is None:
            issue_ids = [r[0] for r in conn.execute(text("""
                SELECT issue_id FROM verification.issues
                WHERE error_type = :t AND status IN ('open', 'reopened') AND fix_batch_id IS NULL"""),
                {"t": error_type}).fetchall()]
        n = conn.execute(text("""
            UPDATE verification.issues SET fix_batch_id = :b, status = 'fixing',
                   rule_id = coalesce(:r, rule_id)
             WHERE issue_id = ANY(:ids) AND status IN ('open', 'reopened')"""),
            {"b": bid, "ids": issue_ids, "r": rule_id}).rowcount
        conn.execute(text("""
            INSERT INTO verification.batch_targets (batch_id, rcept_no)
            SELECT DISTINCT :b, rcept_no FROM verification.issues WHERE fix_batch_id = :b
            ON CONFLICT DO NOTHING"""), {"b": bid})
    return {"batch_id": bid, "issues": n}


def batch_add_targets(batch_id: int, rcepts: list[str]) -> int:
    _require("fix")
    with _Tx() as conn:
        return conn.execute(text("""
            INSERT INTO verification.batch_targets (batch_id, rcept_no)
            SELECT :b, f.rcept_no FROM filings f WHERE f.rcept_no = ANY(:rs)
            ON CONFLICT DO NOTHING"""), {"b": batch_id, "rs": rcepts}).rowcount


def batch_set(batch_id: int, *, status: str | None = None, rule_id: str | None = None,
              note: str | None = None, commit_sha: str | None = None) -> None:
    with _Tx() as conn:
        conn.execute(text("""
            UPDATE verification.fix_batches
               SET status = coalesce(:s, status), rule_id = coalesce(:r, rule_id),
                   note = coalesce(:n, note), commit_sha = coalesce(:c, commit_sha),
                   updated_at = now(),
                   done_at = CASE WHEN :s IN ('done', 'abandoned') THEN now() ELSE done_at END
             WHERE batch_id = :b"""),
            {"b": batch_id, "s": status, "r": rule_id, "n": note, "c": commit_sha})


def _git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True,
                         timeout=60)
    if out.returncode != 0:
        raise VqError(f"git {' '.join(args)} 실패: {out.stderr.strip()}")
    return out.stdout.strip()


def require_clean_pushed_head() -> str:
    """Reloads must be reproducible from a commit that is already on origin/main."""
    commit = parser_commit()
    if commit.endswith("-dirty") or commit == "unknown":
        raise VqError(f"작업트리에 미커밋 변경이 있다({commit}) — 커밋·push 후 재적재할 것.")
    _git("fetch", "-q", "origin", "main")
    ok = subprocess.run(["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", "HEAD",
                         "origin/main"], capture_output=True).returncode == 0
    if not ok:
        raise VqError("HEAD 가 origin/main 에 없다 — `git push origin HEAD:main` 후 재적재할 것"
                      "(검증 러너가 같은 코드를 받아야 한다).")
    return commit


def _reload_rcept(rcept: str, reason: str) -> tuple[str, str | None]:
    """Re-extract one filing from its XML and store body+notes+table meta in ONE
    transaction (same routine as the daily collector/note_lines_sync.py)."""
    from psycopg2 import errors as pg_errors
    from sqlalchemy.exc import DBAPIError

    from collector.db import get_session
    from fin2.extract.report_lines import (extract_report_lines, store_note_lines,
                                           store_report_lines, store_report_tables)

    with get_session() as s:
        t = s.execute(text("""
            SELECT dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
            FROM download_tasks dt JOIN filings f USING (rcept_no)
            WHERE dt.rcept_no = :r AND dt.status = 'completed' AND dt.file_type = 'xml'
              AND dt.file_path IS NOT NULL LIMIT 1"""), {"r": rcept}).fetchone()
    if t is None or not Path(t.file_path).exists():
        return "failed", "XML 원문 없음 — PDF/XBRL 경로는 전용 스크립트로 처리"
    lines = extract_report_lines(t.file_path, rcept_no=rcept, corp_code=t.corp_code,
                                 report_fiscal_year=t.fiscal_year,
                                 report_fiscal_period=t.fiscal_period, include_notes=True)
    if not lines:
        return "failed", "추출 0행 — 기존 적재를 지우지 않고 중단"
    try:
        with get_session() as s:
            s.execute(text("SELECT set_config('verification.load_reason', :r, true)"),
                      {"r": reason})
            store_note_lines(s, rcept, lines)
            store_report_tables(s, rcept, lines)
            store_report_lines(s, rcept, lines)
    except DBAPIError as exc:
        if isinstance(exc.orig, pg_errors.LockNotAvailable):
            return "deferred", "검증 중(lease) — lease 종료 후 재시도"
        return "failed", f"{type(exc.orig).__name__}: {str(exc.orig)[:300]}"
    except ValueError as exc:            # manual-row guard
        return "failed", str(exc)[:300]
    return "done", None


def batch_reload(batch_id: int, limit: int | None = None,
                 shard: tuple[int, int] | None = None) -> dict:
    """`shard=(i, n)` reloads only targets with int(rcept) % n == i, so n processes can
    share one batch without touching the same filing."""
    _require("fix")
    commit = require_clean_pushed_head()
    batch_set(batch_id, status="reloading", commit_sha=commit)
    with engine.connect() as conn:
        targets = [r[0] for r in conn.execute(text("""
            SELECT rcept_no FROM verification.batch_targets
            WHERE batch_id = :b AND status IN ('pending', 'deferred') ORDER BY rcept_no"""),
            {"b": batch_id}).fetchall()]
    if shard:
        targets = [t for t in targets if int(t) % shard[1] == shard[0]]
    if limit:
        targets = targets[:limit]
    tally = {"done": 0, "deferred": 0, "failed": 0}
    for i, rcept in enumerate(targets, 1):
        status, err = _reload_rcept(rcept, f"fix_batch:{batch_id}")
        tally[status] += 1
        with _Tx() as conn:
            conn.execute(text("""
                UPDATE verification.batch_targets SET status = :s, attempts = attempts + 1,
                       last_error = :e, updated_at = now()
                 WHERE batch_id = :b AND rcept_no = :r"""),
                {"s": status, "e": err, "b": batch_id, "r": rcept})
        if i % 50 == 0:
            print(f"  [{i}/{len(targets)}] {tally}", flush=True)
    return {"batch_id": batch_id, "commit": commit, "targets": len(targets), **tally}


def batch_mark_fixed(batch_id: int) -> dict:
    """fixing → fixed for every issue of the batch whose filing was actually reloaded with
    changed data (the trigger enforces it). The rest stay fixing and are listed."""
    _require("fix")
    commit = require_clean_pushed_head()
    fixed, not_changed = [], []
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(text("""
            SELECT issue_id FROM verification.issues
            WHERE fix_batch_id = :b AND status = 'fixing' ORDER BY issue_id"""),
            {"b": batch_id}).fetchall()]
    for iid in ids:
        try:
            with _Tx(evidence=f"fix_batch:{batch_id} @ {commit}") as conn:
                conn.execute(text("""
                    UPDATE verification.issues SET status = 'fixed', fixed_parser_commit = :c
                     WHERE issue_id = :i"""), {"c": commit, "i": iid})
            fixed.append(iid)
        except Exception as exc:  # noqa: BLE001 — trigger refusal is per issue
            not_changed.append((iid, str(getattr(exc, "orig", exc)).splitlines()[0][:200]))
    return {"batch_id": batch_id, "fixed": fixed, "not_fixed": not_changed}


# ═══════════════════════════════ status ═══════════════════════════════
def machine_status(conn) -> dict:
    rows = conn.execute(text("""
        SELECT mc.verdict, mc.audit, (mc.load_seq IS NOT DISTINCT FROM fl.load_seq) AS cur,
               count(*) AS n
        FROM verification.machine_checks mc
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        GROUP BY 1, 2, 3""")).fetchall()
    out: dict = {"current": {}, "stale": 0, "audit": 0}
    for verdict, audit, cur, n in rows:
        if not cur:
            out["stale"] += n
            continue
        out["current"][verdict] = out["current"].get(verdict, 0) + n
        if audit:
            out["audit"] += n
    out["gate"] = "on" if machine_gate_on(conn) else "off"
    from fin2.verification.machine_compare import TOOL_VERSION
    out["tool"] = TOOL_VERSION
    out["unchecked_pending_filings"] = conn.execute(text("""
        SELECT count(*) FROM verification.progress_filings pf
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        LEFT JOIN verification.machine_checks mc USING (rcept_no)
        WHERE pf.status = 'pending'
          AND (mc.rcept_no IS NULL OR mc.load_seq IS DISTINCT FROM fl.load_seq
               OR (mc.tool_version <> :t AND mc.verdict IN ('mismatch', 'error')))"""),
        {"t": TOOL_VERSION}).scalar_one()
    return out


def status() -> dict:
    with engine.connect() as conn:
        machine = machine_status(conn)
        slots = dict(conn.execute(text(
            "SELECT status, count(*) FROM verification.progress GROUP BY 1")).fetchall())
        filings = dict(conn.execute(text(
            "SELECT status, count(*) FROM verification.progress_filings GROUP BY 1")).fetchall())
        issues = dict(conn.execute(text(
            "SELECT status, count(*) FROM verification.issues GROUP BY 1")).fetchall())
        corps_done = conn.execute(text("""
            SELECT count(*) FROM (SELECT corp_code FROM verification.progress
            GROUP BY corp_code HAVING bool_and(status = 'passed')) x""")).scalar_one()
        top200 = conn.execute(text("""
            SELECT count(*) FILTER (WHERE status = 'passed'), count(*)
            FROM verification.progress WHERE corp_rank <= 200""")).fetchone()
        in_progress = [dict(r) for r in conn.execute(text("""
            SELECT corp_code, fiscal_year, fiscal_period, claimed_by, lease_until
            FROM verification.progress WHERE status = 'in_progress'""")).mappings()]
        runs = dict(conn.execute(text("""
            SELECT outcome, count(*) FROM verification.runner_runs
            WHERE started_at > now() - interval '24 hours' GROUP BY 1""")).fetchall())
        pending_decisions = conn.execute(text(
            "SELECT count(*) FROM verification.decisions WHERE status = 'pending'")).scalar_one()
        db_size = conn.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar_one()
        schema_size = conn.execute(text("""
            SELECT pg_size_pretty(coalesce(sum(pg_total_relation_size(c.oid)), 0))
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'verification' AND c.relkind IN ('r', 'm')""")).scalar_one()
    free_gb = shutil.disk_usage("/opt/homebrew/var").free / 2**30 if Path(
        "/opt/homebrew/var").exists() else None
    return {"slots": slots, "filings": filings, "issues": issues, "corps_done": corps_done,
            "top200_passed": top200[0], "top200_total": top200[1], "in_progress": in_progress,
            "runs_24h": runs, "pending_decisions": pending_decisions, "machine": machine,
            "db_size": db_size,
            "verification_schema_size": schema_size,
            "disk_free_gb": round(free_gb, 1) if free_gb is not None else None,
            "at": datetime.now().isoformat(timespec="minutes")}
