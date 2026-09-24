"""Machine pass: compare every pending filing of a slot with its source XML, no model.

Design: docs/plans/verification_machine_compare_design_2026-09-24.md

Per slot (claimed like any verifier, actor '<worktree>:machine'):
- each pending filing without a current machine check is compared (machine_compare.py);
  the result goes to verification.machine_checks at the filing's claimed load_seq;
- clean -> `pass` with a machine note, unless the slot is drawn for the web-view audit
  (kv machine.audit_pct, default 1%): then nothing is passed and the model reviewer compares
  the whole slot as before;
- DB has no statement rows and the source has no statement tables -> `skip`;
- anything else stays pending for the model reviewer, who sees the findings in `vq.py show`.
Filings with open issues are left alone (their re-check belongs to the model reviewer).
"""
from __future__ import annotations

import json
import random

from sqlalchemy import text

from collector.db import engine
from fin2.verification import machine_compare as mc
from fin2.verification import ops
from fin2.verification.ops import Slot

MACHINE_LEASE_MINUTES = 15

# A pending slot the machine has not finished: some pending filing lacks a current check.
NEEDS_MACHINE_SQL = """
    (p.status = 'pending' AND EXISTS (
        SELECT 1 FROM verification.progress_filings pf
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        LEFT JOIN verification.machine_checks mc USING (rcept_no)
        WHERE pf.corp_code = p.corp_code AND pf.fiscal_year = p.fiscal_year
          AND pf.fiscal_period = p.fiscal_period AND pf.status = 'pending'
          AND (mc.rcept_no IS NULL OR mc.load_seq IS DISTINCT FROM fl.load_seq)))"""


def audit_pct(conn) -> float:
    v = conn.execute(text("SELECT value FROM verification.kv WHERE key = 'machine.audit_pct'")).scalar()
    try:
        return float(v) if v is not None else 1.0
    except ValueError:
        return 1.0


def _source_path(conn, rcept: str) -> str | None:
    from pathlib import Path
    for (fp,) in conn.execute(text("""
            SELECT file_path FROM download_tasks
            WHERE rcept_no = :r AND status = 'completed' AND file_type = 'xml'
              AND file_path IS NOT NULL ORDER BY id DESC"""), {"r": rcept}).fetchall():
        if Path(fp).exists():
            return fp
    return None


def _store(conn, rcept: str, load_seq: int, res: mc.Result, audit: bool) -> None:
    conn.execute(text("""
        INSERT INTO verification.machine_checks
            (rcept_no, load_seq, tool_version, verdict, audit, counts, findings, checked_at, checked_by)
        VALUES (:r, :s, :v, :d, :a, CAST(:c AS jsonb), CAST(:f AS jsonb), now(), verification.actor())
        ON CONFLICT (rcept_no) DO UPDATE SET
            load_seq = EXCLUDED.load_seq, tool_version = EXCLUDED.tool_version,
            verdict = EXCLUDED.verdict, audit = EXCLUDED.audit, counts = EXCLUDED.counts,
            findings = EXCLUDED.findings, checked_at = now(), checked_by = verification.actor()"""),
        {"r": rcept, "s": load_seq, "v": mc.TOOL_VERSION, "d": res.verdict, "a": audit,
         "c": json.dumps(dict(res.counts)), "f": json.dumps(res.findings[:200], ensure_ascii=False,
                                                           default=str)})


def _note(res: mc.Result) -> str:
    c = res.counts
    extra = "".join(f" {k}={c[k]}" for k in ("prior_only", "sign_restored") if c.get(k))
    return (f"[machine {mc.TOOL_VERSION}] 원문 XML 재무제표 섹션과 기계 대조 전부 일치 — "
            f"행 {c.get('rows', 0)} · 셀 {c.get('cells', 0)}{extra}")


def verify_slot(slot: Slot) -> dict:
    """Machine-verify the pending filings of an already claimed slot, then release it."""
    out = {"slot": str(slot), "clean": 0, "mismatch": 0, "other": 0, "skipped": 0, "audit": False}
    with engine.connect() as conn:
        filings = [dict(r) for r in conn.execute(text("""
            SELECT pf.rcept_no, pf.claim_load_seq, fl.scope_hashes,
                   (SELECT count(*) FROM verification.issues i
                     WHERE i.rcept_no = pf.rcept_no AND i.status <> 'closed') AS n_open
            FROM verification.progress_filings pf
            LEFT JOIN verification.filing_loads fl USING (rcept_no)
            WHERE pf.corp_code = :c AND pf.fiscal_year = :y AND pf.fiscal_period = :p
              AND pf.status = 'pending'
            ORDER BY pf.seq_in_slot"""), slot.params()).mappings()]
        pct = audit_pct(conn)
        results = []
        for f in filings:
            if f["n_open"]:
                continue
            path = _source_path(conn, f["rcept_no"])
            if path is None:
                res = mc.Result("no_source", mc.Counter(), [{"kind": "no_source"}])
            else:
                res = mc.compare_filing(conn, f["rcept_no"], path)
            results.append((f, res))
    clean = [(f, r) for f, r in results if r.verdict == "clean"]
    # Audit draw per slot, only when the machine would otherwise pass all of it.
    audit = bool(results) and len(clean) == len(results) and random.random() * 100 < pct
    out["audit"] = audit
    with ops._Tx(evidence="machine") as conn:
        for f, r in results:
            _store(conn, f["rcept_no"], f["claim_load_seq"], r, audit and r.verdict == "clean")
    for f, r in results:
        scopes = sorted((f["scope_hashes"] or {}).keys())
        if r.verdict == "clean" and not audit:
            if scopes:
                ops.pass_filing(f["rcept_no"], scopes, _note(r))
                out["clean"] += 1
            else:
                out["other"] += 1
        elif r.verdict == "no_structure" and not scopes:
            ops.skip_filing(f["rcept_no"], f"[machine {mc.TOOL_VERSION}] 원문에 재무제표 섹션 표가 없고 "
                                           f"DB 적재 행도 없음")
            out["skipped"] += 1
        elif r.verdict == "mismatch":
            out["mismatch"] += 1
        else:
            out["other"] += 1
    res = ops.done(slot)
    out["status"] = res["status"]
    return out


def run(limit: int | None = None, log=print) -> dict:
    """Claim and machine-verify slots until none is left (or `limit` slots)."""
    total = {"slots": 0, "clean": 0, "mismatch": 0, "other": 0, "skipped": 0, "audit": 0}
    while limit is None or total["slots"] < limit:
        slot = ops.claim(lease_minutes=MACHINE_LEASE_MINUTES, where=NEEDS_MACHINE_SQL)
        if slot is None:
            break
        try:
            r = verify_slot(slot)
        except Exception as exc:
            ops.release(slot, failed=True, note=f"machine: {type(exc).__name__}: {exc}"[:500])
            log(f"{slot} 실패: {type(exc).__name__}: {exc}")
            continue
        total["slots"] += 1
        for k in ("clean", "mismatch", "other", "skipped"):
            total[k] += r[k]
        total["audit"] += int(r["audit"])
        log(json.dumps(r, ensure_ascii=False))
    return total
