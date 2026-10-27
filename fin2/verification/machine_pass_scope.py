"""Machine pass for the table scopes ('biz'; 'note' later): compare, store, pass or leave.

Per pending filing of a scope (scope_progress_filings) without a current check:
- the filing's load stamp is created if missing (ensure_scope_baseline);
- the source is compared with the scope's machine module (machine_biz);
- the result goes to verification.scope_machine_checks at that load_seq;
- clean -> the filing is passed ('<actor>' + machine note); no_structure with nothing stored ->
  skipped; anything else (mismatch, no_source, error) stays pending: findings are turned into
  issues with `vq.py scope issues-json`, a person or the model reviewer decides.
Filings with open issues are left alone. A filing is "current" when its stored check has the
same load_seq and tool_version, so a reload or a new tool version brings it back automatically.
No model audit sample yet (the model reviewer for scopes is a later step, design doc P5).
"""
from __future__ import annotations

import json

from sqlalchemy import text

from collector.db import engine
from fin2.verification import machine_biz
from fin2.verification import ops

MODULES = {"biz": machine_biz}


def _source_path(conn, rcept: str) -> str | None:
    """Source XML of a filing, preferring the local SD mirror: a stat on the NAS (SMB) costs
    ~0.4 s per file and made the bulk pass IO-bound (measured 2026-10-27, 40 filings/min)."""
    from pathlib import Path
    for (fp,) in conn.execute(text("""
            SELECT CASE WHEN status = 'completed' AND file_type = 'xml' THEN file_path
                        ELSE viewer_xml_path END
            FROM download_tasks
            WHERE rcept_no = :r AND ((status = 'completed' AND file_type = 'xml' AND file_path IS NOT NULL)
                                     OR viewer_xml_path IS NOT NULL)
            ORDER BY id DESC"""), {"r": rcept}).fetchall():
        sd = ops._sd_path(fp)
        if sd != fp or Path(fp).exists():
            return sd
    return None


def pending_filings(conn, scope: str, limit: int | None, shard: tuple[int, int] | None) -> list[str]:
    mod = MODULES[scope]
    rows = conn.execute(text("""
        SELECT pf.rcept_no
        FROM verification.scope_progress_filings pf
        JOIN verification.scope_progress p
          ON p.scope = pf.scope AND p.corp_code = pf.corp_code
         AND p.fiscal_year = pf.fiscal_year AND p.fiscal_period = pf.fiscal_period
        LEFT JOIN verification.scope_loads sl ON sl.rcept_no = pf.rcept_no AND sl.scope = pf.scope
        LEFT JOIN verification.scope_machine_checks mc
               ON mc.rcept_no = pf.rcept_no AND mc.scope = pf.scope
        WHERE pf.scope = :sc AND pf.status = 'pending'
          AND p.status IN ('pending', 'has_issues')
          AND NOT EXISTS (SELECT 1 FROM verification.issues i
                           WHERE i.rcept_no = pf.rcept_no AND i.scope = pf.scope
                             AND i.status <> 'closed')
          AND (mc.rcept_no IS NULL OR sl.rcept_no IS NULL OR mc.load_seq IS DISTINCT FROM sl.load_seq
               OR mc.tool_version <> :tv)
        ORDER BY p.era_rank, p.corp_rank NULLS LAST, pf.fiscal_year DESC, pf.fiscal_period,
                 pf.rcept_no"""), {"sc": scope, "tv": mod.TOOL_VERSION}).fetchall()
    out = [r[0] for r in rows]
    if shard:
        out = [r for r in out if int(r) % shard[1] == shard[0]]
    return out[:limit] if limit else out


def check_one(rcept: str, scope: str) -> str:
    """Compare one filing and record the result. Returns the verdict (or 'stale')."""
    mod = MODULES[scope]
    with engine.connect() as conn:
        path = _source_path(conn, rcept)
        res = None
        if path is not None:
            try:
                res = mod.compare_filing(conn, rcept, path)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the pass
                res = mod.Result(verdict="error", counts={"error": f"{type(exc).__name__}: {exc}"[:300]})
        else:
            res = mod.Result(verdict="no_source", counts={})

    with ops._Tx() as conn:
        f = conn.execute(text("""
            SELECT pf.status, pf.corp_code, pf.fiscal_year, pf.fiscal_period
            FROM verification.scope_progress_filings pf
            WHERE pf.scope = :sc AND pf.rcept_no = :r FOR UPDATE"""),
            {"sc": scope, "r": rcept}).mappings().fetchone()
        if f is None or f["status"] != "pending":
            return "stale"
        seq = conn.execute(text("SELECT verification.ensure_scope_baseline(:r, :sc)"),
                           {"r": rcept, "sc": scope}).scalar()
        conn.execute(text("""
            INSERT INTO verification.scope_machine_checks
                (rcept_no, scope, load_seq, tool_version, verdict, audit, counts, findings,
                 checked_at, checked_by)
            VALUES (:r, :sc, :s, :v, :d, false, CAST(:c AS jsonb), CAST(:f AS jsonb), now(),
                    verification.actor())
            ON CONFLICT (rcept_no, scope) DO UPDATE SET
                load_seq = EXCLUDED.load_seq, tool_version = EXCLUDED.tool_version,
                verdict = EXCLUDED.verdict, audit = false, counts = EXCLUDED.counts,
                findings = EXCLUDED.findings, checked_at = now(),
                checked_by = verification.actor()"""),
            {"r": rcept, "sc": scope, "s": seq, "v": mod.TOOL_VERSION, "d": res.verdict,
             "c": json.dumps(res.counts, ensure_ascii=False),
             "f": json.dumps(res.findings, ensure_ascii=False, default=str)})
        new_status = {"clean": "passed", "no_structure": "skipped"}.get(res.verdict)
        if res.verdict == "no_structure" and res.counts.get("db_tables"):
            new_status = None
        if new_status:
            note = (f"[machine {mod.TOOL_VERSION}] 원문 사업의 내용 표와 기계 대조 전부 일치 — "
                    f"저장 표 {res.counts.get('db_tables', 0)}"
                    if new_status == "passed" else
                    f"[machine {mod.TOOL_VERSION}] 원문에 사업의 내용 섹션이 없고 저장 표도 없음")
            conn.execute(text("""
                UPDATE verification.scope_progress_filings
                   SET status = :st, verified_load_seq = :s, verified_scopes = NULL,
                       verified_at = now(), verified_by = verification.actor() || :sfx,
                       note = :n, updated_at = now()
                 WHERE scope = :sc AND rcept_no = :r"""),
                {"st": new_status, "s": seq, "n": note, "sc": scope, "r": rcept, "sfx": ":machine"})
            conn.execute(text("SELECT verification.refresh_scope_slot(:sc, :c, :y, :p)"),
                         {"sc": scope, "c": f["corp_code"], "y": f["fiscal_year"],
                          "p": f["fiscal_period"]})
    return res.verdict


def run(scope: str, limit: int | None = None, shard: tuple[int, int] | None = None) -> dict:
    ops._require("verify")
    if scope not in MODULES:
        raise ops.VqError(f"기계 모듈이 있는 scope: {', '.join(MODULES)}")
    with engine.connect() as conn:
        todo = pending_filings(conn, scope, limit, shard)
    tally: dict[str, int] = {}
    for i, rcept in enumerate(todo, 1):
        v = check_one(rcept, scope)
        tally[v] = tally.get(v, 0) + 1
        if i % 200 == 0:
            print(f"  [{i}/{len(todo)}] {tally}", flush=True)
    return {"scope": scope, "tool": MODULES[scope].TOOL_VERSION, "checked": len(todo), **tally}
