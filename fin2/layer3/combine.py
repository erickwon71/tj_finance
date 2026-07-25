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
from functools import lru_cache

from sqlalchemy import text

from parser.common.account_mapper import get_mapper
from fin2.standardize.rules import (DIRECT_MAP, CONSUMED_CANON, StdContext,
                                    rule_additive_capex, rule_derive_fcf,
                                    rule_derive_net_debt)
from fin2.layer3.industry_profiles import (
    apply_revenue_profile, norm as _norm_label, NO_REVENUE_CORPS,
)

# grand-total revenue labels (normalized) that outrank component labels in is.revenue
# conflicts (증권/지주: 영업수익 total vs 수수료수익 component).
_REVENUE_TOTAL_LABELS = frozenset({"매출액", "영업수익", "매출", "순매출액"})


@lru_cache(maxsize=200_000)
def _map_label(label_raw: str, fs: str | None):
    """Cached AccountMapper.map — the same face labels (자산총계·매출액…) recur across
    every filing, and map() runs fuzzy Jaro-Winkler over all aliases, so caching by
    (label_raw, fs) is the dominant speedup for the full std_v3 build. Deterministic."""
    return get_mapper().map(label_raw, fs_section=fs)

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


def _period_filings(session, corp: str, fy: int, period: str) -> list[str]:
    """All rcept_no for a (corp, fy, period), most-final/most-recent first."""
    rows = session.execute(text("""
        SELECT rcept_no FROM filings
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
        ORDER BY is_final DESC, filed_at DESC NULLS LAST, rcept_no DESC
    """), {"c": corp, "y": fy, "p": period}).fetchall()
    return [r[0] for r in rows]


def _period_filings_chrono(session, corp: str, fy: int, period: str) -> list[tuple[str, bool]]:
    """(rcept_no, is_amendment) for a period, ORIGINAL first (filed_at ASC).
    Only filings that have report_lines (a base/overlay must have extractable rows)."""
    rows = session.execute(text("""
        SELECT f.rcept_no, COALESCE(f.is_amendment, false)
        FROM filings f
        WHERE f.corp_code=:c AND f.fiscal_year=:y AND f.fiscal_period=:p
          AND EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no=f.rcept_no)
        ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC
    """), {"c": corp, "y": fy, "p": period}).fetchall()
    return [(r[0], bool(r[1])) for r in rows]


# cell identity for delta-patch (measured 2026-07-22: SAME 90.9% under this key).
_CELL_KEY = ("statement", "basis", "col_index", "section_path", "label_raw")


def build_merged_lines(session, corp: str, fy: int, period: str) -> list[dict]:
    """★정본 정책(사용자 2026-07-22): 최초등록본 + 순차 델타 패치.

    Base = the ORIGINAL filing (최초등록본). For each 기재정정 (amendment) in
    chronological order, overlay ONLY the cells whose value differs (edit) or that
    are new (add); cells the amendment does not touch keep the original. Every
    patched/added cell is marked (`amended=True`, `amended_by=<rcept>`,
    `amend_chain=[...]`) so "기재정정 반영" provenance flows downstream.

    Value semantics = P1 (final = as-restated), but constructed as original+deltas
    so partial amendments (첨부정정 / 부분 본문정정) never drop the untouched base.

    Cell identity = (statement, basis, col_index, section_path, label_raw). Measured
    alignment: SAME 90.9% / CHANGED 6.4% / ONLY_ORIG 1.2% / ONLY_AMEND 1.5% over 60
    original↔amendment pairs. ONLY_ORIG (amendment not re-listing a base row) is
    KEPT (no deletion) — safe for the 6 top-level metrics (stable labels); label
    drift on detailed line items is a documented refinement (may double-count a
    renamed detail row, does not affect the top-level metrics).

    Returns a list of merged cell dicts (col_index=0 only), each with:
      statement, basis, col_index, section_path, label_raw, value_won, node_role,
      table_seq, is_cumulative, source_rcept, amended(bool), amended_by, amend_chain.
    """
    chrono = _period_filings_chrono(session, corp, fy, period)
    merged: dict[tuple, dict] = {}
    for i, (rcept, is_amend) in enumerate(chrono):
        # ★ base = the FIRST filing (chrono). Its cells are never "amended" even if that
        # filing is itself a [기재정정] (no earlier original to patch → it IS the base).
        # Only LATER filings (i>0) patch a value or add a new row → amended=True.
        is_base = (i == 0)
        rows = session.execute(text("""
            SELECT statement, basis, col_index, section_path, label_raw, value_won,
                   node_role, table_seq, COALESCE(is_cumulative, false) AS is_cum
            FROM report_lines
            WHERE rcept_no=:r AND col_index=0 AND value_won IS NOT NULL
        """), {"r": rcept}).fetchall()
        for (statement, basis, col_index, section_path, label_raw, value_won,
             node_role, table_seq, is_cum) in rows:
            key = (statement, basis, col_index, section_path, label_raw)
            cell = {
                "statement": statement, "basis": basis, "col_index": col_index,
                "section_path": section_path, "label_raw": label_raw,
                "value_won": int(value_won), "node_role": node_role,
                "table_seq": table_seq, "is_cumulative": bool(is_cum),
            }
            if key not in merged:
                # first occurrence. From the base filing → not amended. From a later
                # filing → a row added by that amendment → amended.
                cell["source_rcept"] = rcept
                cell["amended"] = not is_base
                cell["amended_by"] = None if is_base else rcept
                cell["amend_chain"] = [] if is_base else [rcept]
                merged[key] = cell
            else:
                base = merged[key]
                if not is_base and int(value_won) != base["value_won"]:
                    # value edit by a later filing → patch + mark
                    cell["source_rcept"] = rcept
                    cell["amended"] = True
                    cell["amended_by"] = rcept
                    cell["amend_chain"] = base["amend_chain"] + [rcept]
                    merged[key] = cell
                # equal value, or same base filing duplicate → keep base (no-op)
    return list(merged.values())


def select_canonical_rcept(session, corp: str, fy: int, period: str) -> str | None:
    """L3-1b: pick ONE canonical filing (rcept_no) for a period — the most-final one.

    Kept for diagnostics/back-compat. Prefer select_canonical_rcepts() for
    combine: the single-filing choice is unsafe when the final filing is a
    첨부정정 (attachment-only amendment, body identical to original → no financial
    statements in report_lines) or a 본문정정 whose statements were not extracted.
    """
    fl = _period_filings(session, corp, fy, period)
    return fl[0] if fl else None


def select_canonical_rcepts(session, corp: str, fy: int, period: str,
                            statements=("BS", "IS", "CF")) -> dict[str, str]:
    """L3-1b (per-statement): resolve each statement to the newest filing that
    ACTUALLY contains report_lines for it.

    Rationale (measured 2026-07-22): filing selection must be per-statement, not
    per-filing. The final filing (is_final) can be a 첨부정정 (body identical → no
    statements in report_lines; 321 cases) or a partially/never-extracted 본문정정
    (125). Blindly reading only is_final would yield empty/MISSING. Walking the
    filing chain (is_final → … → original) per statement recovers 307/321
    attachment amendments (use the original body — identical by definition) and
    17/125 body amendments. The rest have no report_lines in any filing = genuine
    data gap (PDF-only / un-extracted), surfaced as MISSING for L3-2 / PDF pass.

    This mirrors the old chain, which stored bs_rcept / is_rcept / cf_rcept
    separately — per-statement source resolution is the proven design.

    Returns {statement: rcept_no} for statements that have report_lines somewhere
    (statements with no data anywhere are simply absent from the dict).
    """
    filings = _period_filings(session, corp, fy, period)
    out: dict[str, str] = {}
    for statement in statements:
        for rcept in filings:  # most-final first
            has = session.execute(text("""
                SELECT 1 FROM report_lines
                WHERE rcept_no=:r AND statement=:s LIMIT 1
            """), {"r": rcept, "s": statement}).fetchone()
            if has:
                out[statement] = rcept
                break
    return out


_INDUTY_CACHE: dict[str, str | None] = {}


def _get_induty(session, corp: str) -> str | None:
    """Cached corp → induty_code (KSIC) lookup (once per corp across the full build)."""
    if corp not in _INDUTY_CACHE:
        r = session.execute(text(
            "SELECT induty_code FROM corporations WHERE corp_code=:c"), {"c": corp}).fetchone()
        _INDUTY_CACHE[corp] = r[0] if r else None
    return _INDUTY_CACHE[corp]


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
    # revenue grand-total preference: a grand-total label (매출액/영업수익) outranks a
    # component label (수수료수익/이자수익/보험영업수익…) that also maps to is.revenue.
    # Fixes securities/holdings where 영업수익 total conflicts with 수수료수익 component
    # (both top-level exact). Insurers under IFRS17 have no such total (or =0) → unaffected.
    if canon == "is.revenue":
        grand = [r for r in rows
                 if _norm_label(r.get("label_raw")) in _REVENUE_TOTAL_LABELS and r["value"]]
        if grand:
            gvals = {r["value"] for r in grand}
            if len(gvals) == 1:
                return next(iter(gvals))
            rows = grand  # multiple grand totals disagree → decide among them below
    def _eps_dup(candidate_vals):
        """Near-equal same-sign values (e.g. original vs restated) -> max-abs, else None."""
        nums = [v for v in candidate_vals if v is not None]
        if len(nums) < 2:
            return None
        hi = max(nums, key=abs)
        lo = min(nums, key=abs)
        if hi == 0 or (hi > 0) != (lo > 0):
            return None
        return hi if abs(hi - lo) / abs(hi) <= _CONFLICT_EPS else None

    vals = {r["value"] for r in rows}
    if len(vals) == 1:
        return next(iter(vals))
    # EPS approx-dup FIRST: an immaterial restatement diff (original vs amended) resolves
    # to max-abs, so the shallowest-depth rule below doesn't override it on a rounding gap.
    dup = _eps_dup(vals)
    if dup is not None:
        return dup
    # shallowest-depth preference: DIRECT_MAP canonicals are statement totals, so the
    # least-nested line outranks deeper sub-items that map to the same canonical
    # (e.g. 'Ⅰ.영업수익' total vs its '보험료수익' children; or IFRS17 '보험서비스수익'
    # at 보험손익 depth-1 vs '수수료수익' at 투자손익>… depth-2). Only fires on an existing
    # conflict, so it can fill a held NULL but never regress a match.
    def _depth(r):
        p = (r.get("section_path") or "").strip()
        return 0 if not p else p.count(">") + 1
    # exclude 0-valued candidates: an IFRS17 empty top-level header (e.g. '영업수익'=0
    # above 보험손익/투자손익 sections) must not win as a shallowest "total".
    pool = [r for r in rows if r["value"] not in (0, None)]
    if not pool:
        return None
    pvals = {r["value"] for r in pool}
    if len(pvals) == 1:
        return next(iter(pvals))          # a single distinct non-zero value
    min_depth = min(_depth(r) for r in pool)
    shallow = [r for r in pool if _depth(r) == min_depth]
    svals = {r["value"] for r in shallow}
    if len(svals) == 1:
        return next(iter(svals))
    return _eps_dup(svals)  # shallowest still split → EPS among them, else hold


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


# P&L 결과 계정(손실이 될 수 있음). 순'손실' 단독 라벨(이익 없음)에 양수값이면 손실을 양(+)으로
# 기재한 서식(루닛 2021 'V.당기순손실'=+73.6B 등) → 표준화 시 부호반전. 이미 음수(괄호기재)이거나
# 결합라벨('이익(손실)')·이익 라벨은 그대로. 실측: 손실단독 net_income 음수 1098 vs 양수 90(7.6%).
_LOSS_CANON = frozenset({
    "is.net_income", "is.operating_income", "is.ebt",
    "is.controlling_ni", "is.gross_profit",
})


def _loss_signed(canon: str, label: str, value):
    """순'손실' 단독 라벨 + 양수 → −value(손실). 그 외는 원값."""
    if (value is not None and value > 0 and canon in _LOSS_CANON
            and label and "손실" in label and "이익" not in label):
        return -value
    return value


def _map_rows(rows, period: str, basis: str, statements) -> dict[str, list[dict]]:
    """Map merged cell dicts → {canonical: [candidate]}. Shared by both paths.
    Interim (H1/Q3) flow (is./cf.) keeps cumulative cells only (std_v2 convention).
    Carries the amendment marker (amended/amended_by) onto each candidate."""
    interim = period in ("H1", "Q3")
    cands: dict[str, list[dict]] = defaultdict(list)
    cum_seen: set[str] = set()
    stmt_set = set(statements)
    for r in rows:
        if r["statement"] not in stmt_set or r["basis"] != basis:
            continue
        fs = _FS.get(r["statement"])
        res = _map_label(r["label_raw"], fs)
        if res.confidence < 0.88 or res.account_code.startswith("unknown."):
            continue
        c = res.account_code
        is_cum = r["is_cumulative"]
        flow = interim and (c.startswith("is.") or c.startswith("cf."))
        if flow:
            if is_cum:
                if c not in cum_seen:
                    cands.pop(c, None)
                    cum_seen.add(c)
            elif c in cum_seen:
                continue
        cands[c].append({
            "value": _loss_signed(c, r["label_raw"], r["value_won"]),
            "stage": res.stage, "label_raw": r["label_raw"],
            "node_role": r["node_role"], "section_path": r["section_path"],
            "table_seq": r["table_seq"], "is_cumulative": is_cum,
            "amended": r.get("amended", False), "amended_by": r.get("amended_by"),
        })
    return dict(cands)


def collect_candidates(session, corp: str, fy: int, period: str, basis: str,
                       statements=("BS", "IS"),
                       rcept_by_stmt: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """Map current-year (col_index=0) report_lines to {canonical: [candidate]} by
    querying report_lines directly (diagnostic / ablation path).

    rcept_by_stmt: optional {statement: rcept_no} to restrict each statement to a
    single filing. Without it, ALL filings for the period are pooled — which pools
    original + amendment/restatement versions and produces spurious conflicts.
    combine() uses build_merged_lines() instead (delta-patch); this stays for the
    ablation/pooled diagnostics.
    """
    rows = []
    for statement in statements:
        params = {"c": corp, "y": fy, "p": period, "b": basis, "s": statement}
        rcept_clause = ""
        if rcept_by_stmt and rcept_by_stmt.get(statement):
            rcept_clause = " AND rcept_no = :r"
            params["r"] = rcept_by_stmt[statement]
        db_rows = session.execute(text(f"""
            SELECT label_raw, value_won, node_role, section_path, table_seq,
                   COALESCE(is_cumulative, false) AS is_cum
            FROM report_lines
            WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
              AND basis=:b AND statement=:s AND col_index=0 AND value_won IS NOT NULL
              {rcept_clause}
        """), params).fetchall()
        for label_raw, value_won, node_role, section_path, table_seq, is_cum in db_rows:
            rows.append({
                "statement": statement, "basis": basis, "label_raw": label_raw,
                "value_won": int(value_won), "node_role": node_role,
                "section_path": section_path, "table_seq": table_seq,
                "is_cumulative": bool(is_cum),
            })
    return _map_rows(rows, period, basis, statements)


def combine(session, corp: str, fy: int, period: str, basis: str,
            rcept_by_stmt: dict[str, str] | None = None,
            select_filing: bool = True, statements=("BS", "IS")):
    """Assemble std columns for one period. Returns (col, conflicts).

    col: {std_column: value} for DIRECT_MAP canonicals that resolved to a single
    value. conflicts: {canonical: [held candidates]} for analysis.

    Default path (L3-1b, 정본 정책): build_merged_lines() — 최초등록본 + 순차 델타
    패치(기재정정 반영 표시 포함). This removes spurious conflicts from pooling
    versions AND preserves untouched base cells under partial amendments.

    rcept_by_stmt: explicit {statement: rcept_no} bypasses the merge (ablation).
    select_filing=False + no rcept_by_stmt: pool all filings (diagnostic).
    """
    col, conflicts, _prov = combine_full(
        session, corp, fy, period, basis,
        rcept_by_stmt=rcept_by_stmt, select_filing=select_filing, statements=statements)
    return col, conflicts


def combine_full(session, corp: str, fy: int, period: str, basis: str,
                 rcept_by_stmt: dict[str, str] | None = None,
                 select_filing: bool = True, statements=("BS", "IS", "CF"),
                 merged: list[dict] | None = None):
    """Like combine() but also returns provenance (for std_v3 build, L3-3).

    Returns (col, conflicts, prov) where prov = {
      basis_fallback: bool,
      amended_cols:   [std_col, ...]         # value came from a 기재정정-patched cell
      amend_chain:    {std_col: [rcept,...]} # which amendments touched it
    }. source_rcepts is resolved by the caller (build) from the merged filings.

    merged: pre-built build_merged_lines() result. Pass it to reuse the (basis-
    independent) delta-patch merge across both bases — halves the query cost in
    the full build.
    """
    prov = {"basis_fallback": False, "amended_cols": [], "amend_chain": {}}
    if rcept_by_stmt is not None:
        cands = collect_candidates(session, corp, fy, period, basis,
                                   statements=statements, rcept_by_stmt=rcept_by_stmt)
    elif select_filing:
        if merged is None:
            merged = build_merged_lines(session, corp, fy, period)
        cands = _map_rows(merged, period, basis, statements)
        # L3-2 basis fallback: a company with no subsidiaries files only 별도(separate);
        # its 연결(consolidated) figures = separate. When the requested basis is entirely
        # absent but the period has only the other basis, fall back (verified: 45/45 such
        # cases are single-basis companies whose other-basis value == std_v2). Mirrors the
        # old chain (consolidated→separate for non-consolidating corps).
        if not cands:
            other = "separate" if basis == "consolidated" else "consolidated"
            bases_present = {r["basis"] for r in merged}
            if bases_present == {other}:
                cands = _map_rows(merged, period, other, statements)
                prov["basis_fallback"] = True
    else:
        cands = collect_candidates(session, corp, fy, period, basis,
                                   statements=statements)
    confirmed, conflicts = _resolve(cands)
    col: dict[str, int] = {}
    for canon, value in confirmed.items():
        std_col = DIRECT_MAP.get(canon)
        if std_col is None:
            continue
        col[std_col] = value
        # amendment provenance: did the winning value come from a 기재정정-patched cell?
        amend_rcepts = [r["amended_by"] for r in cands.get(canon, [])
                        if r["value"] == value and r.get("amended") and r.get("amended_by")]
        if amend_rcepts:
            prov["amended_cols"].append(std_col)
            # dedupe preserving order
            prov["amend_chain"][std_col] = list(dict.fromkeys(amend_rcepts))

    # industry revenue profile (P1): for insurers etc. whose K-IFRS IS diverges from the
    # general 매출액 standard, standardized revenue = Σ named subtotals, and the components
    # are preserved for the industry-aware tearsheet. Only the build/select path (which has
    # the raw merged lines) applies this; diagnostic (pooled/rcept) paths skip it.
    if merged is not None and rcept_by_stmt is None:
        is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        if not is_lines and prov["basis_fallback"]:
            other = "separate" if basis == "consolidated" else "consolidated"
            is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == other]
        applied = apply_revenue_profile(is_lines, _get_induty(session, corp), corp)
        if applied:
            pname, revenue, components = applied
            col["revenue"] = revenue
            prov["industry_lines"] = {"profile": pname, **components}
    # 증권성 금융지주: 매출액 개념이 없으므로 revenue 는 NULL(사실). DIRECT_MAP 이 수수료수익 등
    # 성분을 revenue 로 오선택했거나 bank 프로파일이 gross 를 억지로 채운 것을 제거. op_income
    # 이하는 그대로 유지(정확 적재됨).
    if corp in NO_REVENUE_CORPS:
        col.pop("revenue", None)
        if prov.get("industry_lines"):
            prov["industry_lines"] = None
    # enrichment (v3-native, 2026-07-25): capex/fcf/net_debt = report_lines-native, reusing
    # the v2 standardize rules against the confirmed canonicals. Additive-only — writes new
    # columns without mutating the existing DIRECT_MAP cols (debt/lease additive rules are NOT
    # run here to avoid perturbing validated columns; net_debt uses v3's own debt/cash).
    # D&A·EBITDA·shares_out·data_quality come from separate backfills (cf_da·shares·DQ), not here.
    _apply_enrichment(corp, fy, period, basis, confirmed, col)
    return col, conflicts, prov


def _apply_enrichment(corp, fy, period, basis, confirmed, col):
    """Compute capex/fcf/net_debt in-place on `col` by reusing the v2 standardize rules on
    the confirmed canonicals. Additive: only sets the three new keys, never mutates the
    existing DIRECT_MAP cols. net_debt derives from v3's own short/long debt + cash (v3 debt
    diverges from v2 for some firms — a pre-existing base-mapping matter tracked for G2, not
    fixed here). D&A·EBITDA·shares_out·data_quality come from separate backfills."""
    ctx = StdContext(corp_code=corp, fiscal_year=fy, fiscal_period=period,
                     basis=basis, canon=dict(confirmed), col=dict(col))
    rule_additive_capex(ctx)     # capex = -(|유형자산취득| + |무형자산취득|)  [cf.capex canonicals]
    rule_derive_fcf(ctx)         # fcf = cfo - |capex|
    rule_derive_net_debt(ctx)    # net_debt = (short+long debt) - cash  [v3's own values]
    for k in ("capex", "fcf", "net_debt"):
        v = ctx.col.get(k)
        if v is not None:
            col[k] = v
