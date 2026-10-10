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
from sqlalchemy.exc import IntegrityError

from collector.db import engine
from fin2.verification import machine_compare as mc
from fin2.verification import ops
from fin2.verification.ops import Slot

MACHINE_LEASE_MINUTES = 15

# A pending slot the machine has not finished: some pending filing lacks a current check.
NEEDS_MACHINE_SQL = """
    (p.status IN ('pending', 'has_issues') AND EXISTS (
        SELECT 1 FROM verification.progress_filings pf
        LEFT JOIN verification.filing_loads fl USING (rcept_no)
        LEFT JOIN verification.machine_checks mc USING (rcept_no)
        WHERE pf.corp_code = p.corp_code AND pf.fiscal_year = p.fiscal_year
          AND pf.fiscal_period = p.fiscal_period AND pf.status = 'pending'
          -- a pending filing whose check is from another tool version is re-checked whatever its
          -- verdict (2026-10-10: clean-by-mc9 filings held back by auto issues that were later
          -- closed as out of scope stayed pending forever)
          AND (mc.rcept_no IS NULL OR mc.load_seq IS DISTINCT FROM fl.load_seq
               OR mc.tool_version <> '""" + mc.TOOL_VERSION + """')))"""


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


_UNIT = {1: "원", 1_000: "천원", 1_000_000: "백만원", 100_000_000: "억원"}
AUTO_ISSUE_KINDS = {"sign_omitted"}


def sign_issues(res: mc.Result) -> list[dict]:
    """Issues the machine registers itself for a cell whose sign alone breaks the SCE roll-forward
    and whose flip closes it exactly, with no other candidate (the source dropped the parentheses).

    R0-2 (user decision 2026-10-10): layer 2 keeps the printed value, so this is a source defect,
    not a layer-2 one. A cell whose layer-3 correction already flips it (`l3_covered`, set by
    machine_compare.compare_filing) gets no issue; the rest are `source_defect` — a candidate for
    a layer-3 correction step (camp_err_review F5)."""
    out, seen = [], set()
    for f in res.findings:
        if f["kind"] != "sign_omitted" or f.get("l3_covered"):
            continue
        # the same row label recurs in every year block: the block's closing row tells them
        # apart (one active issue per cell - ux_vissues_active_cell)
        col = f"{f.get('header') or '열' + str(f['col'])} @ {f['to']}"[:200]
        key = (f["basis"], f["row"][:300], col)
        if key in seen:
            continue
        seen.add(key)
        s = f.get("scale") or 1
        v = f["value"]
        out.append({
            "basis": f["basis"], "statement": "SCE", "account_label": f["row"][:300],
            "column_label": col,
            "db_value": int(round(v * s)), "source_value": int(round(-v * s)),
            "source_value_raw": f"{abs(v):,.0f}" if v >= 0 else f"({abs(v):,.0f})",
            "source_unit": _UNIT.get(s, "원"), "error_type": "source_defect", "rule_id": "R0-2",
            "evidence": (f"[machine {mc.TOOL_VERSION}] 자본변동표 열 '{f.get('header')}' {f['from']}→{f['to']} "
                         f"롤포워드가 닫히지 않고(차이 {f['diff']:,.0f}), 이 셀 부호만 뒤집으면 정확히 닫힌다"
                         f"(다른 후보 없음). DB 는 원문 그대로({v:,.0f}) — 원문 괄호 누락 추정. "
                         f"계층3 보정 없음 → 계층3 보정 규칙 후보(R0-2)."),
        })
    return out


# Finding kinds that are plain cell facts read off the source - convertible to issues once the
# reviewer confirmed a sample in the web view. Identity/table findings need judgement.
CELL_KINDS = ("value", "missing_row", "zero_row", "uncovered_cell", "extra_row", "sign_omitted")


def _raw(v) -> str:
    """Source-style cell text: 1,234 / (1,234) / '-'."""
    if not isinstance(v, (int, float)) or v == 0:
        return "-" if v in (0, None) else str(v)
    return f"{v:,.0f}" if v >= 0 else f"({-v:,.0f})"


def _sce_column_label(f: dict) -> str | None:
    """verify_prompt.md field format: SCE '<DB col_label (or source header)> @ <block closing
    date>' so the same row label in two year blocks gives two keys; other statements: no
    column (report_lines.col_label is NULL for BS/IS/CF, so a header there only broke recheck)."""
    if f.get("statement") != "SCE":
        return None
    col = f.get("db_col") or f.get("header")
    end = f.get("block_end")
    if not end:
        return col
    return f"{col} @ {mc.label_date(end) or end}"


def arith_issues(res: mc.Result) -> list[dict]:
    """source_defect issues for SCE identities the printed numbers themselves break (sce_arith
    with src_broken: D-calc and S-calc both open, verify_prompt I3). Registered by the machine
    only for filings that are otherwise clean (user decision 2026-10-09: from mc7 on); in a
    mismatch filing the model reviewer registers them with the rest."""
    out, seen = [], set()
    for f in res.findings:
        if f["kind"] != "sce_arith" or not f.get("src_broken") or f.get("l3_covered"):
            continue   # R0-2: an identity the layer-3 corrections close is handled there
        s = f.get("scale") or 1
        when = mc.label_date(f["to"]) or f["to"]
        col = f"{f.get('header') or '열' + str(f['col'])} @ {when} #항등식"[:200]
        key = (f["basis"], f["to"][:300], col)
        if key in seen:
            continue
        seen.add(key)
        what = "기말→다음 기초 이월" if f["check"] == "carry" else "롤포워드"
        out.append({
            "basis": f["basis"], "statement": "SCE", "account_label": f["to"][:300], "column_label": col,
            "db_value": int(round(f["end"] * s)), "source_value": int(round(f.get("src_end", f["end"]) * s)),
            "source_value_raw": _raw(f.get("src_end", f["end"])), "source_unit": _UNIT.get(s, "원"),
            "error_type": "source_defect", "rule_id": "R0-1",
            "evidence": (f"[machine {mc.TOOL_VERSION}] 자본변동표 열 '{f.get('header')}' {f['from']}→{f['to']} {what}: "
                         f"D-계산 {f['sum']:,.0f}, 기말 {f['end']:,.0f}, 차이 {f['diff']:,.0f}(표시단위) — "
                         f"원문 숫자로도 닫히지 않음(원문 산수 불일치, 사용자 결정 (가)). 원인 판단은 수정 쪽."),
        })
    return out


# Evidence prefix of issues the model reviewer confirmed in the web view and registered from
# machine findings (issues-json). Machine-only registrations keep "[machine mcN]" - the fix side
# tells the two apart (camp_err_review CLAUDE.local.md F5).
CONFIRMED_PREFIX = "[확인 " + mc.TOOL_VERSION + "]"
IDENTITY_KINDS = ("sce_identity", "sce_arith", "sign_omitted", "bs_identity")


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.5


def cell_error_type(f: dict) -> tuple[str, str]:
    """error_type of a `value` finding by the symptom table of verify_prompt.md (first match),
    computed from the numbers so every model gets the same answer, plus an evidence note."""
    s = f.get("scale") or 1
    d = f.get("db")
    src = f.get("src")
    if not isinstance(src, (int, float)) or not isinstance(d, (int, float)):
        return "value_mismatch", "원문 셀이 숫자가 아님"
    sv = src * s
    if sv == 0:
        return "value_mismatch", "원문 빈 칸"
    if d == 0:
        return "value_mismatch", "DB 빈 칸"
    if _close(d, -sv):
        return "sign_flip", ""
    for n in range(-9, 10):
        if n and (_close(d, sv * 10 ** n) or _close(d, -sv * 10 ** n)):
            return "unit_scale", f"DB = 원문 × 10^{n}" + (" (부호도 다름)" if _close(d, -sv * 10 ** n) else "")
    if f.get("found_at"):
        return ("column_misassign" if f["statement"] == "SCE" else "period_misassign"), ""
    return "value_mismatch", ""


def identity_issue(f: dict, prefix: str) -> dict | None:
    """source_defect item for an identity finding (verify_prompt I3), or None when the printed
    numbers close it (I2 - no source_defect; the D != S cells are registered as cell issues)."""
    if f["kind"] == "bs_identity":
        s = 1
        d = f.get("assets")
        return {"basis": f["basis"], "statement": "BS", "account_label": "자산총계",
                "column_label": "#항등식", "db_value": d, "source_value": d,
                "source_unit": None, "error_type": "source_defect", "rule_id": "R0-1",
                "evidence": f"{prefix} BS 자산 {f.get('assets'):,} ≠ 부채 {f.get('liabilities'):,} + 자본 "
                            f"{f.get('equity'):,} (차이 {f.get('diff'):,}원)"}
    if not f.get("src_broken"):
        return None
    s = f.get("scale") or 1
    when = mc.label_date(f["to"]) or f["to"]
    col = f"{f.get('db_col') or f.get('header') or '열' + str(f['col'])} @ {when} #항등식"[:200]
    what = "기말→다음 기초 이월" if f["check"] == "carry" else "롤포워드"
    src_end = f.get("src_end", f["end"])   # printed closing (mc8); older findings: DB value only
    return {"basis": f["basis"], "statement": "SCE", "account_label": f["to"][:300], "column_label": col,
            "db_value": int(round(f["end"] * s)), "source_value": int(round(src_end * s)),
            "source_value_raw": _raw(src_end), "source_unit": _UNIT.get(s, "원"),
            "error_type": "source_defect", "rule_id": "R0-1",
            "evidence": (f"{prefix} 자본변동표 열 '{f.get('header')}' {f['from']}→{f['to']} {what}: "
                         f"D-계산 {f['sum']:,.0f}, 기말 {f['end']:,.0f}, 차이 {f['diff']:,.0f}(표시단위) — "
                         f"원문 숫자로도 닫히지 않음(I3)")}


def findings_to_issues(findings: list[dict], kinds=CELL_KINDS, select: list[int] | None = None,
                       prefix: str | None = None) -> list[dict]:
    """Issue items (vq.py issue add --json-file) for the cell-fact findings of one filing.

    `select`: 1-based finding numbers as `vq.py show` prints them; then every selected finding
    is converted whatever its kind (identity findings -> source_defect). The `(#n)` suffix for a
    label repeated in one table is assigned over ALL findings of the filing first, so the same
    cell gets the same key whichever subset is registered."""
    prefix = prefix or f"[machine {mc.TOOL_VERSION}]"
    out, seen = [], set()
    # mc10 (2026-10-10): identity findings are layer-3 backlog, never issues (see INFO_KINDS)
    wanted = set(select or ())
    for no, f in enumerate(findings, 1):
        kind = f["kind"]
        if select is not None:
            if no not in wanted:
                if kind in ("value", "missing_row", "zero_row", "uncovered_cell", "extra_row"):
                    _cell_item(f, prefix, seen)       # reserve its (#n) key
                continue
            if kind in IDENTITY_KINDS:
                continue
            if kind not in ("value", "missing_row", "zero_row", "uncovered_cell", "extra_row"):
                continue
        elif kind not in kinds or kind in IDENTITY_KINDS:
            continue
        out.append(_cell_item(f, prefix, seen))
    return out


def _cell_item(f: dict, prefix: str, seen: set) -> dict:
    kind = f["kind"]
    s = f.get("scale") or 1
    item = {"basis": f["basis"], "statement": f["statement"], "account_label": (f.get("label") or "")[:300],
            "column_label": None, "source_unit": _UNIT.get(s, "원")}
    if kind == "value":
        src = f.get("src")
        et, note = cell_error_type(f)
        item.update(column_label=_sce_column_label(f), db_value=f.get("db"),
                    source_value=int(round(src * s)) if isinstance(src, (int, float)) else None,
                    source_value_raw=_raw(src), error_type=et,
                    evidence=f"{prefix} DB {f.get('db')} ≠ 원문 기대열({f.get('header')}) "
                             f"{src}; 같은 값이 있는 열 {f.get('found_at')}, 부호만 다른 열 {f.get('flipped_at')}"
                             + (f" — {note}" if note else ""))
    elif kind in ("missing_row", "zero_row"):
        cells = f.get("cells") or []
        nums = [c for c in cells if isinstance(c, (int, float))]
        # BS/IS/CF: the current-period cell; SCE: the first component that moved
        cur = (next((c for c in nums if c), 0.0) if f["statement"] == "SCE"
               else (nums[0] if nums else None))
        item.update(source_value=int(round(cur * s)) if cur is not None else 0,
                    source_value_raw=_raw(cur), error_type="missing_row",
                    evidence=f"{prefix} 원문 행이 DB 에 없음 (원문 셀 {cells[:6]})"
                             + (" — 전열 '-'" if kind == "zero_row" else ""))
    elif kind == "uncovered_cell":
        src = f.get("src")
        item.update(column_label=_sce_column_label(f), source_value=int(round(src * s)) if src else None,
                    source_value_raw=_raw(src), error_type="missing_row",
                    evidence=f"{prefix} 원문 SCE 셀({f.get('header')}={src})이 DB 에 없음")
    elif kind == "extra_row":
        item.update(error_type="extra_row", evidence=f"{prefix} DB 행이 원문 표에 없음")
    key = (item["basis"], item["statement"], item["account_label"], item["column_label"])
    n = 2
    while key in seen:  # the same label recurs across year blocks
        item["account_label"] = f"{(f.get('label') or '')[:280]} (#{n})"
        key = (item["basis"], item["statement"], item["account_label"], item["column_label"])
        n += 1
    seen.add(key)
    return {k: v for k, v in item.items() if v is not None}


def _all_no_fix(conn, rcept: str, res: mc.Result) -> int:
    """Number of findings if every non-info finding is a cell fact on a cell the fix side
    already concluded "no code fix needed" for (closed no_fix issue, same DB value), else 0.

    The column is not compared: the reviewer's issue and the machine finding label the column
    differently (or not at all), while label + DB value already pin the cell in a filing."""
    kinds = {x["kind"] for x in res.findings if x["kind"] not in mc.INFO_KINDS}
    if not kinds or not kinds <= set(CELL_KINDS):
        return 0
    items = findings_to_issues(res.findings)
    for it in items:
        hit = conn.execute(text(f"""
            SELECT 1 FROM verification.issues i
            JOIN LATERAL (SELECT e.evidence FROM verification.issue_events e
                          WHERE e.issue_id = i.issue_id AND e.to_status = 'closed'
                          ORDER BY e.at DESC, e.event_id DESC LIMIT 1) e ON true
            WHERE i.rcept_no = :r AND i.basis = :b AND i.statement = :s
              AND i.account_label = :a AND i.status = 'closed'
              AND i.db_value IS NOT DISTINCT FROM CAST(:v AS numeric)
              AND {ops._NO_FIX_CLOSE_SQL}
            LIMIT 1"""), {"r": rcept, "b": it["basis"], "s": it["statement"],
                         "a": it["account_label"], "v": it.get("db_value")}).fetchone()
        if hit is None:
            return 0
    return len(items)


def verify_slot(slot: Slot) -> dict:
    """Machine-verify the pending filings of an already claimed slot, then release it."""
    out = {"slot": str(slot), "clean": 0, "mismatch": 0, "auto_issue": 0, "other": 0, "skipped": 0,
           "audit": False}
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
        known = {f["rcept_no"]: _all_no_fix(conn, f["rcept_no"], r)
                 for f, r in results if r.verdict == "mismatch"}
    clean = [(f, r) for f, r in results if r.verdict == "clean"]
    # Audit draw per slot, only when the machine would otherwise pass all of it.
    audit = bool(results) and len(clean) == len(results) and random.random() * 100 < pct
    out["audit"] = audit
    with ops._Tx(evidence="machine") as conn:
        for f, r in results:
            _store(conn, f["rcept_no"], f["claim_load_seq"], r, audit and r.verdict == "clean")
    for f, r in results:
        scopes = sorted((f["scope_hashes"] or {}).keys())
        # mc10 (2026-10-10): identity findings (source arithmetic, suspected dropped parentheses)
        # are layer-3 backlog, not layer-2 issues — the machine registers nothing for them.
        if r.verdict == "clean" and not audit:
            if scopes:
                ops.pass_filing(f["rcept_no"], scopes, _note(r))
                out["clean"] += 1
            else:
                out["other"] += 1
        elif r.verdict == "mismatch" and known.get(f["rcept_no"]) and scopes:
            # only re-findings of cells concluded "no code fix needed" (source defect / false
            # report) — a model run would just re-find them (2026-10-03)
            ops.pass_filing(f["rcept_no"], scopes,
                            f"{_note(r)} · 불일치 {known[f['rcept_no']]}건 모두 no_fix 결론 셀(원문결함·오탐)")
            out["clean"] += 1
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
    total = {"slots": 0, "clean": 0, "mismatch": 0, "auto_issue": 0, "other": 0, "skipped": 0, "audit": 0}
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
        for k in ("clean", "mismatch", "auto_issue", "other", "skipped"):
            total[k] += r[k]
        total["audit"] += int(r["audit"])
        log(json.dumps(r, ensure_ascii=False))
    return total


def _issue_key(i: dict) -> tuple:
    return (i["basis"], i["account_label"], i.get("column_label"))


def recheck_slot(slot: Slot) -> dict:
    """Close or reopen the machine's own fixed issues of an already claimed slot by comparing
    the reloaded filing again: an issue whose sign finding is gone is closed, one that still
    shows up is reopened. Then release the slot (filings with all issues closed go back to
    pending, and the next `machine run` passes them if they are clean)."""
    out = {"slot": str(slot), "closed": 0, "reopened": 0, "skipped": 0}
    with engine.connect() as conn:
        issues = [dict(r) for r in conn.execute(text("""
            SELECT i.issue_id, i.rcept_no, i.basis, i.account_label, i.column_label
            FROM verification.issues i
            WHERE i.corp_code = :c AND i.fiscal_year = :y AND i.fiscal_period = :p
              AND i.status = 'fixed' AND i.created_by LIKE '%machine'"""), slot.params()).mappings()]
        by_rcept: dict[str, list[dict]] = {}
        for i in issues:
            by_rcept.setdefault(i["rcept_no"], []).append(i)
        still: dict[str, set] = {}
        for rcept in by_rcept:
            path = _source_path(conn, rcept)
            if path is None:
                continue
            res = mc.compare_filing(conn, rcept, path)
            still[rcept] = {_issue_key(x) for x in sign_issues(res) + arith_issues(res)}
    for rcept, items in by_rcept.items():
        if rcept not in still:
            out["skipped"] += len(items)
            continue
        for i in items:
            if _issue_key(i) in still[rcept]:
                ops.transition(i["issue_id"], "reopened",
                               f"[machine {mc.TOOL_VERSION}] 재적재 후에도 같은 발견이 남음"
                               f"(부호 누락 또는 원문 산수 불일치)")
                out["reopened"] += 1
            else:
                ops.transition(i["issue_id"], "closed",
                               f"[machine {mc.TOOL_VERSION}] 재적재 후 이 발견이 사라짐(롤포워드 닫힘)")
                out["closed"] += 1
    if out["skipped"]:
        # source XML missing: releasing as failed keeps recheck() from claiming the same slot
        # forever (it stays has_issues with a fixed issue); blocked after 3 tries like any slot
        ops.release(slot, failed=True, note=f"machine recheck: 원문 XML 없음 {out['skipped']}건")
        out["status"] = "released_failed"
        return out
    res = ops.done(slot)
    out["status"] = res["status"]
    return out


RECHECK_SQL = """
    (p.status = 'has_issues' AND EXISTS (
        SELECT 1 FROM verification.issues i
        WHERE i.corp_code = p.corp_code AND i.fiscal_year = p.fiscal_year
          AND i.fiscal_period = p.fiscal_period AND i.status = 'fixed'
          AND i.created_by LIKE '%machine'))"""


def recheck(limit: int | None = None, log=print) -> dict:
    total = {"slots": 0, "closed": 0, "reopened": 0, "skipped": 0}
    while limit is None or total["slots"] < limit:
        slot = ops.claim(lease_minutes=MACHINE_LEASE_MINUTES, where=RECHECK_SQL)
        if slot is None:
            break
        try:
            r = recheck_slot(slot)
        except Exception as exc:
            ops.release(slot, failed=True, note=f"machine recheck: {type(exc).__name__}: {exc}"[:500])
            log(f"{slot} 실패: {type(exc).__name__}: {exc}")
            continue
        total["slots"] += 1
        for k in ("closed", "reopened", "skipped"):
            total[k] += r[k]
        log(json.dumps(r, ensure_ascii=False))
    return total


def repass(limit: int | None = None, log=print) -> dict:
    """Machine re-comparison of filings passed before the machine existed (legacy / model
    web-view verdicts; user decision 2026-09-25). Clean keeps the pass and records the check.
    Anything else demotes the filing to pending and drops the check, so the next
    `machine run` handles it like any unchecked filing (pass / auto issue / model review)."""
    if ops.role() != "admin":
        raise ops.VqError("machine repass 는 admin(main) 전용 — passed 판정을 되돌리기 때문")
    total = {"checked": 0, "kept": 0, "demoted": 0, "no_source": 0}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pf.rcept_no, pf.corp_code, pf.fiscal_year, pf.fiscal_period
            FROM verification.progress_filings pf
            LEFT JOIN verification.machine_checks mc USING (rcept_no)
            WHERE pf.status = 'passed' AND coalesce(pf.verified_by, '') NOT LIKE '%machine'
              AND mc.rcept_no IS NULL
            ORDER BY pf.rcept_no""")).fetchall()
    for n, (rcept, corp, fy, fp) in enumerate(rows):
        if limit is not None and n >= limit:
            break
        with engine.connect() as conn:
            path = _source_path(conn, rcept)
            if path is None:
                total["no_source"] += 1
                continue
            res = mc.compare_filing(conn, rcept, path)
        total["checked"] += 1
        with ops._Tx(evidence=f"[machine repass {mc.TOOL_VERSION}] {res.verdict}") as conn:
            seq = conn.execute(text("SELECT verification.ensure_baseline(:r)"), {"r": rcept}).scalar_one()
            if res.verdict == "clean":
                _store(conn, rcept, seq, res, False)
                total["kept"] += 1
                continue
            conn.execute(text("""
                UPDATE verification.progress_filings
                   SET status = 'pending',
                       note = left(coalesce(note || ' / ', '') || :n, 2000), updated_at = now()
                 WHERE rcept_no = :r AND status = 'passed'"""),
                {"r": rcept, "n": f"[machine repass {mc.TOOL_VERSION}] 기계 재대조 {res.verdict} "
                                  f"{dict((k, v) for k, v in res.counts.items() if k not in ('rows', 'cells'))}"
                                  f" → 재검토"})
            conn.execute(text("DELETE FROM verification.machine_checks WHERE rcept_no = :r"), {"r": rcept})
            conn.execute(text("SELECT verification.refresh_slot(:c, :y, :p)"), {"c": corp, "y": fy, "p": fp})
            total["demoted"] += 1
        if total["checked"] % 200 == 0:
            log(json.dumps(total, ensure_ascii=False))
    return total
