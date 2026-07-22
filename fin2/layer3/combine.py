"""Layer 3 combination engine — PROTOTYPE (L3-1).

Assembles std metrics for one (corp, fiscal_year, fiscal_period, basis) directly
from Layer 2 `report_lines`, reusing the label catalog (AccountMapper) validated
by the Option-A probe (docs/qa/layer3_option_a_probe_2026-07-22.md, DIFF≈0).

Design (hybrid, per docs/plans/layer3_rebuild_plan_2026-07-22.md §1):
  - Port the old chain's conflict resolution (build._resolve / _reduce_conflict)
    — single→confirm, else keep strictest mapping stage, else auto-reduce, else
    HOLD (missing > wrong). No max-abs, no guessing.
  - Adapt signals: old chain discriminated non-current / broad accounts by acode;
    report_lines has no acode, so we use `label_raw` for those regex checks.
  - Carry structural signals (node_role, section_path, table_seq) on every
    candidate so residual conflicts can be analysed and a node_role-based rule
    added *from evidence* in a measured second iteration (not blind).

Scope of the prototype: DIRECT_MAP metrics only (the 6 probe metrics are all
direct-mapped). Additive/derived rules (D&A, debt sums, EBITDA…) come later.

Read-only: this module never writes to the DB.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text

from parser.common.account_mapper import get_mapper
from fin2.standardize.rules import DIRECT_MAP, CONSUMED_CANON

# mapping-stage provenance rank (exact/normalized beat fuzzy). Mirrors build._STAGE_RANK.
_STAGE_RANK = {"exact": 3, "normalized": 2, "guard": 2, "fuzzy": 1, None: 0}

_CONFLICT_EPS = 0.001
_CURRENT_STRICT = {"bs.trade_receivables", "bs.trade_payables",
                   "bs.short_term_debt", "bs.current_bonds"}
_NONCURRENT_RE = re.compile(r"장기|비유동")
_NARROW_PREFER = {"bs.trade_receivables", "bs.trade_payables"}
_BROAD_RE = re.compile(r"및기타|및 기타|AndOther")

# statement -> AccountMapper fs_section hint
_FS = {"IS": "is", "BS": "bs", "CF": "cf"}
# canonical prefix -> statement it is read from
_STMT_OF_PREFIX = {"bs": "BS", "is": "IS", "cf": "CF"}


def select_canonical_rcept(session, corp: str, fy: int, period: str) -> str | None:
    """L3-1b filing selection: pick ONE canonical filing (rcept_no) for a period.

    Rule (leverages the download layer's already-computed `is_final`, which marks
    the final [기재정정] within a period_end_date group). Verified against std_v2:
    is_final agrees with the old chain's choice on 97.5% of 2015+ FY filings.

      1. Prefer is_final=True. Tie-break (29 dup groups exist) = latest filed_at,
         then max rcept_no (deterministic).
      2. Fallback (no is_final): latest filed_at among all filings for the period.

    ⚠ Known edge (2.5%): a many-years-later [기재정정] (소급재작성) is is_final but the
    old chain kept the original — that refinement is deferred (L3-2 / L3-4 parity).
    This selector treats the latest amendment as canonical; restatement handling is
    a separate rule to layer on top.

    Returns rcept_no, or None if the period has no filing.
    """
    row = session.execute(text("""
        SELECT rcept_no FROM filings
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
        ORDER BY is_final DESC, filed_at DESC NULLS LAST, rcept_no DESC
        LIMIT 1
    """), {"c": corp, "y": fy, "p": period}).fetchone()
    return row[0] if row else None


def _reduce_conflict(canon: str, top: list[dict]) -> int | None:
    """Confirm a split top-candidate set WITHOUT guessing, else None (hold).

    Ported from build._reduce_conflict; the acode-based checks are re-expressed
    against label_raw because report_lines carries no acode.
    """
    rows = top
    # narrow-prefer: drop broad '및기타/AndOther' accounts when a pure one exists
    if canon in _NARROW_PREFER:
        narrow = [r for r in rows if not _BROAD_RE.search(r.get("label_raw") or "")]
        if narrow:
            rows = narrow
    # current-strict: a current canonical must not absorb non-current (장기/비유동) rows
    if canon in _CURRENT_STRICT:
        cur = [r for r in rows if not _NONCURRENT_RE.search(r.get("label_raw") or "")]
        if cur:
            rows = cur
    vals = {r["value"] for r in rows}
    if len(vals) == 1:
        return next(iter(vals))
    # EPS approx-dup: same sign + relative error <= EPS -> representative (max-abs)
    nums = [v for v in vals if v is not None]
    if len(nums) >= 2:
        hi = max(nums, key=abs)
        lo = min(nums, key=abs)
        if hi == 0 or (hi > 0) != (lo > 0):
            return None
        if abs(hi - lo) / abs(hi) <= _CONFLICT_EPS:
            return hi
    return None


def _resolve(cands: dict[str, list[dict]]):
    """{canonical: [candidate]} -> (confirmed {canonical: value}, conflicts {canonical: [candidate]}).

    Ported from build._resolve. Conflicts are HELD (not filled) and returned for
    analysis (only for consumed canonicals, to avoid lineage noise).
    """
    confirmed: dict[str, int] = {}
    conflicts: dict[str, list[dict]] = {}
    for c, rows in cands.items():
        vals = {r["value"] for r in rows}
        if len(vals) == 1:
            confirmed[c] = next(iter(vals))
            continue
        best = max(_STAGE_RANK.get(r.get("stage"), 0) for r in rows)
        top = [r for r in rows if _STAGE_RANK.get(r.get("stage"), 0) == best]
        top_vals = {r["value"] for r in top}
        if len(top_vals) == 1:
            confirmed[c] = next(iter(top_vals))
            continue
        reduced = _reduce_conflict(c, top)
        if reduced is not None:
            confirmed[c] = reduced
            continue
        if c in CONSUMED_CANON:
            conflicts[c] = sorted(top, key=lambda r: (r["value"] is None, r["value"]))
    return confirmed, conflicts


def collect_candidates(session, corp: str, fy: int, period: str, basis: str,
                       statements=("BS", "IS"),
                       rcept_by_stmt: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """Map current-year (col_index=0) report_lines to {canonical: [candidate]}.

    Each candidate: {value, stage, label_raw, node_role, section_path, table_seq,
    is_cumulative}. Interim (H1/Q3) flow (is./cf.) keeps cumulative cells only,
    mirroring the std_v2 storage convention (build._collect).

    rcept_by_stmt: optional {statement: rcept_no} to restrict each statement to a
    single filing. Without it, ALL filings for the period are pooled — which pools
    original + amendment/restatement versions and produces spurious conflicts
    until Layer-2 pass-4 (정본 선택) or a filing-selection step is applied.
    """
    mapper = get_mapper()
    interim = period in ("H1", "Q3")
    cands: dict[str, list[dict]] = defaultdict(list)
    cum_seen: set[str] = set()

    for statement in statements:
        fs = _FS.get(statement)
        params = {"c": corp, "y": fy, "p": period, "b": basis, "s": statement}
        rcept_clause = ""
        if rcept_by_stmt and rcept_by_stmt.get(statement):
            rcept_clause = " AND rcept_no = :r"
            params["r"] = rcept_by_stmt[statement]
        rows = session.execute(text(f"""
            SELECT label_raw, value_won, node_role, section_path, table_seq,
                   COALESCE(is_cumulative, false) AS is_cum
            FROM report_lines
            WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
              AND basis=:b AND statement=:s AND col_index=0 AND value_won IS NOT NULL
              {rcept_clause}
        """), params).fetchall()

        for label_raw, value_won, node_role, section_path, table_seq, is_cum in rows:
            res = mapper.map(label_raw, fs_section=fs)
            if res.confidence < 0.88 or res.account_code.startswith("unknown."):
                continue
            c = res.account_code
            flow = interim and (c.startswith("is.") or c.startswith("cf."))
            if flow:
                if is_cum:
                    if c not in cum_seen:
                        cands.pop(c, None)
                        cum_seen.add(c)
                elif c in cum_seen:
                    continue
            cands[c].append({
                "value": int(value_won), "stage": res.stage, "label_raw": label_raw,
                "node_role": node_role, "section_path": section_path,
                "table_seq": table_seq, "is_cumulative": bool(is_cum),
            })
    return dict(cands)


def combine(session, corp: str, fy: int, period: str, basis: str,
            rcept_by_stmt: dict[str, str] | None = None,
            select_filing: bool = True):
    """Assemble std columns for one filing. Returns (col, conflicts).

    col: {std_column: value} for DIRECT_MAP canonicals that resolved to a single
    value. conflicts: {canonical: [held candidates]} for analysis.

    select_filing (L3-1b): when True (default) and no explicit rcept_by_stmt is
    given, restrict every statement to the canonical filing chosen by
    select_canonical_rcept() — this removes the spurious conflicts caused by
    pooling original + amendment + restatement versions. Set False to pool all
    filings (diagnostic).
    """
    if rcept_by_stmt is None and select_filing:
        rcept = select_canonical_rcept(session, corp, fy, period)
        if rcept:
            rcept_by_stmt = {"BS": rcept, "IS": rcept, "CF": rcept}
    cands = collect_candidates(session, corp, fy, period, basis,
                               rcept_by_stmt=rcept_by_stmt)
    confirmed, conflicts = _resolve(cands)
    col: dict[str, int] = {}
    for canon, value in confirmed.items():
        std_col = DIRECT_MAP.get(canon)
        if std_col is not None:
            col[std_col] = value
    return col, conflicts
